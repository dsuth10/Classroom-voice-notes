"""Unit tests for Step 9: Capability-scoped Outbound Worker V2."""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.worker.journal import WorkerJournal
from app.worker.outbound_worker_v2 import FatalWorkerError, OutboundWorkerV2


@pytest.fixture
def temp_journal(tmp_path: Path) -> WorkerJournal:
    db_path = tmp_path / "test_worker_journal.db"
    return WorkerJournal(db_path=db_path)


@pytest.fixture
def base_worker_env(monkeypatch) -> None:
    monkeypatch.setenv("CVN_EDGE_BASE_URL", "https://example.supabase.co/functions/v1")
    monkeypatch.setenv("CVN_WORKER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("CVN_WORKER_HMAC_SECRET", "test-hmac-secret")
    monkeypatch.setenv("CVN_WORKER_ID", "test-worker-v2-1")


def test_missing_config_raises_fatal_error(monkeypatch) -> None:
    monkeypatch.delenv("CVN_EDGE_BASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("CVN_WORKER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("CVN_WORKER_HMAC_SECRET", raising=False)

    with pytest.raises(FatalWorkerError) as exc_info:
        OutboundWorkerV2()
    assert "Missing configuration" in str(exc_info.value)


from app.destinations.canonical_json import compute_canonical_content_hash

def test_record_only_routing_success(base_worker_env, temp_journal, tmp_path: Path) -> None:
    export_file = tmp_path / "outbound_records.csv"
    worker = OutboundWorkerV2(journal=temp_journal)

    content_data = {
        "title": "Test Record",
        "category": "Notes",
        "summary": "Summary text",
    }
    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", content_data)

    item = {
        "item_id": "rec-item-100",
        "lease_token": "lease-secret-12345",
        "payload_hash": f"sha256:{valid_hash}",
        "content_hash": valid_hash,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "rec-item-100",
            "source_device_id": "dev-01",
            "created_at": "2026-08-03T10:00:00Z",
            "content_hash": valid_hash,
            "content": content_data,
            "privacy": {
                "automatic_classification": "non_sensitive",
                "risk_level": "low",
                "release_basis": "automatic_policy",
                "checks_passed": ["content_classification_pass"],
            },
        },
    }

    with patch.object(worker, "_send_edge_rpc") as mock_rpc, \
         patch("app.destinations.record_consumer.get_app_data_dir", return_value=tmp_path):

        # Edge complete responds success
        mock_rpc.return_value = (200, {"completed": True})

        processed = worker.process_item(item)
        assert processed is True

        # Check journal state
        journal_entry = temp_journal.get_entry("rec-item-100")
        assert journal_entry is not None
        assert journal_entry["state"] == "remote_completed"
        assert journal_entry["consumer_kind"] == "record_only"


def test_unsupported_routing_fails_closed(base_worker_env, temp_journal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    # Item kind agent_task with target hermes -> should fail closed
    item = {
        "item_id": "task-hermes-101",
        "lease_token": "lease-secret-67890",
        "payload_hash": "sha256:p101",
        "content_hash": "sha256:c101",
        "item_kind": "agent_task",
        "target_agent": "hermes",
        "payload": {"item_id": "task-hermes-101"},
    }

    with patch.object(worker, "_send_edge_rpc") as mock_rpc:
        mock_rpc.return_value = (200, {"failed": True})

        processed = worker.process_item(item)
        assert processed is False

        # Fail RPC should be called with retryable=False
        assert mock_rpc.called
        call_args = mock_rpc.call_args_list[0]
        path_suffix, payload = call_args[0]
        assert path_suffix == "cvn-fail-outbound-item"
        assert payload["retryable"] is False


def test_journal_recovery_bypasses_consumer(base_worker_env, temp_journal, tmp_path: Path) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    item_id = "rec-item-lost-complete"
    payload_hash = "sha256:p200"
    content_hash = "sha256:c200"

    # Pre-populate journal as consumer_succeeded_pending_remote_complete
    temp_journal.record_claim(item_id, payload_hash, content_hash, "record_only")
    temp_journal.record_consumer_success(item_id, "export_row_200")

    # Item is re-claimed with NEW lease token
    reclaimed_item = {
        "item_id": item_id,
        "lease_token": "NEW-lease-secret-99999",
        "payload_hash": payload_hash,
        "content_hash": content_hash,
        "item_kind": "record_only",
        "target_agent": "",
        "payload": {"item_id": item_id},
    }

    with patch.object(worker, "route_and_process") as mock_route, \
         patch.object(worker, "_send_edge_rpc") as mock_rpc:

        mock_rpc.return_value = (200, {"completed": True})

        processed = worker.process_item(reclaimed_item)
        assert processed is True

        # Consumer execution was bypassed!
        assert not mock_route.called

        # Remote complete RPC was called with new lease token
        assert mock_rpc.called
        call_args = mock_rpc.call_args
        path_suffix, payload = call_args[0]
        assert path_suffix == "cvn-complete-outbound-item"
        assert payload["lease_token"] == "NEW-lease-secret-99999"

        # Journal is now remote_completed
        assert temp_journal.get_entry(item_id)["state"] == "remote_completed"


def test_http_401_triggers_fatal_worker_error(base_worker_env, temp_journal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    with patch.object(worker, "_send_edge_rpc", side_effect=FatalWorkerError("Authentication failure: HTTP 401")):
        with pytest.raises(FatalWorkerError):
            worker.claim_item()


def test_transient_network_error_applies_backoff(base_worker_env, temp_journal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    with patch.object(worker, "_send_edge_rpc", side_effect=OSError("Network unreachable")), \
         patch("time.sleep") as mock_sleep:

        claimed = worker.claim_item()
        assert claimed is None
        assert mock_sleep.called
        assert worker.backoff_current > worker.poll_interval
