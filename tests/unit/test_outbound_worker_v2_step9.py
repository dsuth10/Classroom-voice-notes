"""Comprehensive Unit Tests for Step 9: Capability-Scoped Outbound Worker V2 & Senior Gate Remediation."""

import json
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.destinations.canonical_json import compute_canonical_content_hash
from app.worker.errors import GatewayAuthenticationError, GatewayConfigurationError
from app.worker.journal import JournalIdentityConflictError, WorkerJournal
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


def test_missing_hmac_secret_raises_fatal_error(monkeypatch) -> None:
    monkeypatch.setenv("CVN_EDGE_BASE_URL", "https://example.supabase.co/functions/v1")
    monkeypatch.setenv("CVN_WORKER_BEARER_TOKEN", "test-bearer")
    monkeypatch.delenv("CVN_WORKER_HMAC_SECRET", raising=False)

    with pytest.raises(FatalWorkerError) as exc_info:
        OutboundWorkerV2()
    assert "CVN_WORKER_HMAC_SECRET" in str(exc_info.value)


def test_record_only_routing_success(base_worker_env, temp_journal, tmp_path: Path) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    content_data = {
        "title": "Test Record Title",
        "category": "Notes",
        "summary": "Summary text",
    }
    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", content_data)

    item = {
        "item_id": "rec-item-100",
        "lease_token": "test_mock_lease_token_100",
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

        mock_rpc.return_value = (200, {"completed": True})

        processed = worker.process_item(item)
        assert processed is True

        # Check top-level result_reference passed to Edge RPC
        call_args = mock_rpc.call_args[0]
        assert call_args[0] == "cvn-complete-outbound-item"
        assert "result_reference" in call_args[1]
        assert call_args[1]["result_reference"] == "rec-item-100"

        # Check journal state
        journal_entry = temp_journal.get_entry("rec-item-100")
        assert journal_entry is not None
        assert journal_entry["state"] == "remote_completed"


def test_agent_task_routing_and_idempotency_headers(base_worker_env, temp_journal, monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "test-gateway-token")
    worker = OutboundWorkerV2(journal=temp_journal)

    task_data = {
        "instructions": json.dumps({"task_type": "classroom_note.summary", "payload": {"text": "Summarize note"}}),
        "title": "Task Title",
    }
    _, valid_hash = compute_canonical_content_hash("agent_task", "openclaw", None, task_data)

    item = {
        "item_id": "agent-task-200",
        "lease_token": "test_mock_lease_token_200",
        "payload_hash": f"sha256:{valid_hash}",
        "content_hash": valid_hash,
        "item_kind": "agent_task",
        "target_agent": "openclaw",
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "agent_task",
            "target_agent": "openclaw",
            "item_id": "agent-task-200",
            "content_hash": valid_hash,
            "task": task_data,
        },
    }

    with patch.object(worker, "_send_edge_rpc") as mock_rpc, \
         patch("requests.post") as mock_post:

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"output": "Summary result text"}
        mock_post.return_value = mock_post_resp

        mock_rpc.return_value = (200, {"completed": True})

        processed = worker.process_item(item)
        assert processed is True

        # Verify Idempotency-Key headers passed to OpenClaw Gateway
        assert mock_post.called
        headers = mock_post.call_args[1]["headers"]
        assert headers.get("Idempotency-Key") == "cvn-agent-task-200"
        assert headers.get("X-Idempotency-Key") == "cvn-agent-task-200"


def test_gateway_auth_failure_raises_fatal_worker_error(base_worker_env, temp_journal, monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "bad-gateway-token")
    worker = OutboundWorkerV2(journal=temp_journal)

    task_data = {
        "instructions": json.dumps({"task_type": "classroom_note.summary", "payload": {"text": "Summarize note"}}),
    }
    _, valid_hash = compute_canonical_content_hash("agent_task", "openclaw", None, task_data)

    item = {
        "item_id": "agent-task-auth-fail",
        "lease_token": "test_mock_lease_token_auth",
        "payload_hash": f"sha256:{valid_hash}",
        "content_hash": valid_hash,
        "item_kind": "agent_task",
        "target_agent": "openclaw",
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "agent_task",
            "target_agent": "openclaw",
            "item_id": "agent-task-auth-fail",
            "content_hash": valid_hash,
            "task": task_data,
        },
    }

    with patch("requests.post") as mock_post, \
         patch.object(worker, "fail_item") as mock_fail:

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 401
        mock_post.return_value = mock_post_resp

        # Must raise FatalWorkerError without calling remote fail_item RPC
        with pytest.raises(FatalWorkerError):
            worker.process_item(item)

        assert not mock_fail.called


def test_claim_validation_hash_mismatch_fails_closed(base_worker_env, temp_journal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    item = {
        "item_id": "item-hash-mismatch",
        "lease_token": "test_mock_lease_token_mismatch",
        "payload_hash": "sha256:fake",
        "content_hash": "a" * 64,  # Contradicts canonical content hash
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "item-hash-mismatch",
            "content_hash": "a" * 64,
            "content": {"title": "Different Title"},
        },
    }

    with patch.object(worker, "fail_item") as mock_fail:
        mock_fail.return_value = True

        processed = worker.process_item(item)
        assert processed is False

        assert mock_fail.called
        call_args = mock_fail.call_args
        assert call_args[0][0] == "item-hash-mismatch"
        assert "PERMANENT_CLAIM_INVALID" in call_args[0][2]
        assert call_args[1].get("retryable") is False  # retryable=False


def test_journal_identity_conflict_raises_and_fails_closed(base_worker_env, temp_journal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    # Pre-populate journal with original identity
    temp_journal.record_claim("item-conflict-1", "hash_A", "hash_A", "record_only")

    # Claim re-submitted with DIFFERENT content hash
    conflicting_item = {
        "item_id": "item-conflict-1",
        "lease_token": "test_mock_lease_token_conflict",
        "payload_hash": "hash_A",
        "content_hash": "b" * 64,  # Conflicting hash!
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "item-conflict-1",
            "content_hash": "b" * 64,
            "content": {"title": "Test Title"},
        },
    }

    with patch.object(worker, "validate_claimed_item", return_value=conflicting_item["payload"]), \
         patch.object(worker, "fail_item") as mock_fail:

        mock_fail.return_value = True
        processed = worker.process_item(conflicting_item)
        assert processed is False

        assert mock_fail.called
        call_args = mock_fail.call_args
        assert call_args[0][0] == "item-conflict-1"
        assert call_args[0][2] == "JOURNAL_IDENTITY_CONFLICT"
        assert call_args[1].get("retryable") is False  # retryable=False


def test_log_hygiene_redacts_secrets_and_leases(base_worker_env, temp_journal, caplog) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    secret_lease = "SUPER_SECRET_LEASE_TOKEN_12345"
    content_data = {"title": "Sensitive Record Title"}
    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", content_data)

    item = {
        "item_id": "item-log-hygiene",
        "lease_token": secret_lease,
        "payload_hash": f"sha256:{valid_hash}",
        "content_hash": valid_hash,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "item-log-hygiene",
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

    with patch.object(worker, "_send_edge_rpc", return_value=(200, {"completed": True})), \
         caplog.at_level(logging.INFO):

        worker.process_item(item)

        captured_text = caplog.text
        # Secrets and plaintext lease tokens MUST be absent from log text
        assert secret_lease not in captured_text
        assert "test-hmac-secret" not in captured_text
        assert "test-bearer-token" not in captured_text


def test_startup_reconciliation_logs_pending_count(base_worker_env, temp_journal, caplog) -> None:
    temp_journal.record_claim("pending-item-1", "h1", "h1", "record_only")
    temp_journal.record_consumer_success("pending-item-1", "ref_1")

    worker = OutboundWorkerV2(journal=temp_journal)
    with caplog.at_level(logging.INFO):
        worker.reconcile_pending_journal_entries()
        assert "STARTUP_RECONCILIATION: Found 1 pending journal entries" in caplog.text
