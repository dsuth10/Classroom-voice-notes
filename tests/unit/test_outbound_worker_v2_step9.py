"""Comprehensive Unit Tests for Step 9: Capability-Scoped Outbound Worker V2 & Senior Gate Remediation."""

import json
import logging
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.destinations.canonical_json import compute_canonical_content_hash
from app.worker.errors import ExecutionTimeoutUnknown
from app.worker.journal import JournalIdentityConflictError, WorkerJournal
from app.worker.outbound_worker_v2 import FatalWorkerError, OutboundWorkerV2


@pytest.fixture
def temp_journal(tmp_path: Path) -> WorkerJournal:
    db_path = tmp_path / "test_worker_journal.db"
    return WorkerJournal(db_path=db_path)


@pytest.fixture
def base_worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVN_EDGE_BASE_URL", "https://example.supabase.co/functions/v1")
    monkeypatch.setenv("CVN_WORKER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("CVN_WORKER_HMAC_SECRET", "test-hmac-secret")
    monkeypatch.setenv("CVN_WORKER_ID", "test-worker-v2-1")


def test_missing_hmac_secret_raises_fatal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVN_EDGE_BASE_URL", "https://example.supabase.co/functions/v1")
    monkeypatch.setenv("CVN_WORKER_BEARER_TOKEN", "test-bearer")
    monkeypatch.delenv("CVN_WORKER_HMAC_SECRET", raising=False)

    with pytest.raises(FatalWorkerError) as exc_info:
        OutboundWorkerV2()
    assert "CVN_WORKER_HMAC_SECRET" in str(exc_info.value)


def test_production_claim_format_validation(base_worker_env: None, temp_journal: WorkerJournal, tmp_path: Path) -> None:
    """Verifies that plain 64-hex payload_hash and ISO-8601 TIMESTAMPTZ lease_expires_at pass validation."""
    worker = OutboundWorkerV2(journal=temp_journal)

    content_data: Dict[str, Any] = {
        "title": "Test Production Record Title",
        "category": "Notes",
        "summary": "Summary text",
    }
    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", content_data)

    item: Dict[str, Any] = {
        "item_id": "rec-prod-100",
        "lease_token": "test_mock_lease_token_100",
        "payload_hash": valid_hash,  # Plain 64-character lowercase hex string from DB
        "content_hash": valid_hash,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "rec-prod-100",
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

    validated_payload = worker.validate_claimed_item(item)
    assert validated_payload["item_id"] == "rec-prod-100"


def test_agent_task_routing_and_idempotency_headers(base_worker_env: None, temp_journal: WorkerJournal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "test-gateway-token")
    worker = OutboundWorkerV2(journal=temp_journal)

    task_data: Dict[str, Any] = {
        "instructions": json.dumps({"task_type": "classroom_note.summary", "payload": {"text": "Summarize note"}}),
        "title": "Task Title",
    }
    _, valid_hash = compute_canonical_content_hash("agent_task", "openclaw", None, task_data)

    item: Dict[str, Any] = {
        "item_id": "agent-task-200",
        "lease_token": "test_mock_lease_token_200",
        "payload_hash": valid_hash,
        "content_hash": valid_hash,
        "item_kind": "agent_task",
        "target_agent": "openclaw",
        "lease_expires_at": time.time() + 600.0,
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

        # Verify Idempotency-Key headers and request payload idempotencyKey passed to OpenClaw Gateway
        assert mock_post.called
        post_kwargs = mock_post.call_args[1]
        headers = post_kwargs["headers"]
        req_json = post_kwargs["json"]

        assert req_json.get("idempotencyKey") == "cvn-agent-task-200"
        assert req_json.get("idempotency_key") == "cvn-agent-task-200"
        assert headers.get("Idempotency-Key") == "cvn-agent-task-200"
        assert headers.get("X-Idempotency-Key") == "cvn-agent-task-200"


def test_openclaw_unknown_outcome_quarantine_prevents_reexecution(base_worker_env: None, temp_journal: WorkerJournal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "test-gateway-token")
    worker = OutboundWorkerV2(journal=temp_journal)

    task_data: Dict[str, Any] = {
        "instructions": json.dumps({"task_type": "classroom_note.summary", "payload": {"text": "Summarize note"}}),
    }
    _, valid_hash = compute_canonical_content_hash("agent_task", "openclaw", None, task_data)

    item: Dict[str, Any] = {
        "item_id": "agent-task-quarantine-1",
        "lease_token": "test_mock_lease_token_unk",
        "payload_hash": valid_hash,
        "content_hash": valid_hash,
        "item_kind": "agent_task",
        "target_agent": "openclaw",
        "lease_expires_at": time.time() + 600.0,
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "agent_task",
            "target_agent": "openclaw",
            "item_id": "agent-task-quarantine-1",
            "content_hash": valid_hash,
            "task": task_data,
        },
    }

    with patch("app.destinations.openclaw_adapter.OpenClawAdapter.execute", side_effect=ExecutionTimeoutUnknown("Read timeout after POST")), \
         patch.object(worker, "fail_item") as mock_fail:

        # Initial claim attempt times out
        processed = worker.process_item(item)
        assert processed is False
        assert not mock_fail.called

        # Journal state MUST be execution_outcome_unknown
        entry = temp_journal.get_entry("agent-task-quarantine-1")
        assert entry is not None
        assert entry["state"] == "execution_outcome_unknown"

    # Now simulate worker reclaiming the same item after lease expiration
    reclaimed_item: Dict[str, Any] = dict(item)
    reclaimed_item["lease_token"] = "test_new_reclaimed_lease_token_999"

    with patch("app.destinations.openclaw_adapter.OpenClawAdapter.execute") as mock_execute:
        # Reclaimed execution MUST be quarantined and refuse to execute OpenClaw again!
        reclaim_processed = worker.process_item(reclaimed_item)
        assert reclaim_processed is False
        assert not mock_execute.called


def test_lease_margin_expired_fails_claim(base_worker_env: None, temp_journal: WorkerJournal) -> None:
    """Verifies that remaining lease duration less than max consumer runtime + safety margin is rejected."""
    worker = OutboundWorkerV2(journal=temp_journal)

    task_data: Dict[str, Any] = {
        "instructions": json.dumps({"task_type": "classroom_note.summary", "payload": {"text": "Summarize note"}}),
    }
    _, valid_hash = compute_canonical_content_hash("agent_task", "openclaw", None, task_data)

    item: Dict[str, Any] = {
        "item_id": "item-lease-margin-expired",
        "lease_token": "test_mock_lease_token_expired",
        "payload_hash": valid_hash,
        "content_hash": valid_hash,
        "item_kind": "agent_task",
        "target_agent": "openclaw",
        "lease_expires_at": time.time() + 200.0,  # 200s remaining (< 330s required for 300s max OpenClaw execution)
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "agent_task",
            "target_agent": "openclaw",
            "item_id": "item-lease-margin-expired",
            "content_hash": valid_hash,
            "task": task_data,
        },
    }

    with patch.object(worker, "fail_item") as mock_fail:
        processed = worker.process_item(item)
        assert processed is False

        assert mock_fail.called
        assert mock_fail.call_args[0][0] == "item-lease-margin-expired"
        assert "LEASE_EXPIRED_BEFORE_EXECUTION" in mock_fail.call_args[0][2]
        assert mock_fail.call_args[1].get("retryable") is True


def test_strict_claim_validation_target_mismatch(base_worker_env: None, temp_journal: WorkerJournal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    item: Dict[str, Any] = {
        "item_id": "item-target-mismatch",
        "lease_token": "test_mock_lease_token_mismatch",
        "payload_hash": "a" * 64,
        "content_hash": "b" * 64,
        "item_kind": "record_only",
        "target_agent": "auto",  # Forbidden target!
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "auto",
            "item_id": "item-target-mismatch",
            "content_hash": "b" * 64,
            "content": {"title": "Title"},
        },
    }

    with pytest.raises(ValueError) as exc_info:
        worker.validate_claimed_item(item)
    assert "forbidden" in str(exc_info.value)


def test_real_startup_status_reconciliation(base_worker_env: None, temp_journal: WorkerJournal) -> None:
    # 1. Populate journal with pending item
    temp_journal.record_claim("reconcile-item-1", "a" * 64, "b" * 64, "record_only")
    temp_journal.record_consumer_success("reconcile-item-1", "export_ref_101")

    worker = OutboundWorkerV2(journal=temp_journal)

    with patch.object(worker, "_send_edge_rpc") as mock_rpc:
        # Edge returns status == completed
        mock_rpc.return_value = (200, {"found": True, "status": "completed"})

        worker.reconcile_pending_journal_entries()

        # Verify journal entry transitioned to remote_completed
        entry = temp_journal.get_entry("reconcile-item-1")
        assert entry is not None
        assert entry["state"] == "remote_completed"


def test_typed_health_snapshot(base_worker_env: None, temp_journal: WorkerJournal) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)
    snapshot = worker.get_health_snapshot()

    assert snapshot["worker_id"] == "test-worker-v2-1"
    assert snapshot["claim_count"] == 0
    assert snapshot["complete_count"] == 0
    assert snapshot["error_count"] == 0
    assert snapshot["last_claim_at"] is None
    assert snapshot["last_complete_at"] is None


def test_log_hygiene_redacts_secrets_and_leases(base_worker_env: None, temp_journal: WorkerJournal, caplog: pytest.LogCaptureFixture) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)

    secret_lease = "SUPER_SECRET_LEASE_TOKEN_12345"
    content_data: Dict[str, Any] = {"title": "Sensitive Record Title"}
    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", content_data)

    item: Dict[str, Any] = {
        "item_id": "item-log-hygiene",
        "lease_token": secret_lease,
        "payload_hash": valid_hash,
        "content_hash": valid_hash,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "lease_expires_at": time.time() + 600.0,
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
        assert "WORKER_EXECUTION_TIMING" in captured_text
        assert "duration_ms=" in captured_text


def test_completion_payload_records_execution_duration(
    base_worker_env: None,
    temp_journal: WorkerJournal,
) -> None:
    worker = OutboundWorkerV2(journal=temp_journal)
    content_data: Dict[str, Any] = {"title": "Timing test"}
    _, valid_hash = compute_canonical_content_hash(
        "record_only", "openclaw", content_data
    )
    item: Dict[str, Any] = {
        "item_id": "item-execution-timing",
        "lease_token": "test_mock_lease_token_timing",
        "payload_hash": valid_hash,
        "content_hash": valid_hash,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "lease_expires_at": time.time() + 600.0,
        "payload": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "item-execution-timing",
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

    with patch.object(worker, "complete_item", return_value=True) as complete_item:
        assert worker.process_item(item) is True

    result_payload = complete_item.call_args.args[4]
    assert result_payload["execution_duration_ms"] >= 0
