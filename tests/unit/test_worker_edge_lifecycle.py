"""Unit tests verifying Python worker to Edge Function authentication and lifecycle contracts."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.config.settings import SettingsManager
from app.destinations.external_outbox import ExternalOutbox
from app.destinations.outbound_review_store import OutboundReviewStore
from app.destinations.outbound_submission_service import OutboundSubmissionService
from scripts.outbound_worker_v2 import OutboundWorkerV2


def test_outbox_submission_retry_idempotency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that re-submitting an approved item reuses the existing outbox entry without building fresh nonces."""
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")
    settings = SettingsManager()
    settings.set("external_agent.source_device_id", "cvn-device-test-999")

    review_store = OutboundReviewStore(tmp_path / "review.db")
    outbox = ExternalOutbox(tmp_path / "outbox.db")
    submission_svc = OutboundSubmissionService(
        settings_manager=settings, review_store=review_store, outbox=outbox
    )

    item_id = "CVNI-20260802-180000-IDEM"
    draft_dict = {
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {"title": "Test Title"},
        "task": None,
    }
    assessment_json = json.dumps({
        "automatic_classification": "non_sensitive",
        "risk_level": "low",
        "findings": [],
    })

    review_store.create_review_item(
        item_id=item_id,
        note_path=str(tmp_path / "note.md"),
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft_dict),
        assessment_json=assessment_json,
        status="awaiting_review",
    )
    review_store.approve(item_id, approval_method="manual_ui")

    # First submission -> creates outbox row
    first_item = submission_svc.submit_approved_item(item_id)
    assert first_item is not None
    first_outbox = outbox.get_by_task_id(item_id)
    assert first_outbox is not None
    first_idempotency_key = first_outbox["idempotency_key"]

    # Reset status back to approved_pending_enqueue to simulate retry
    import sqlite3
    with sqlite3.connect(review_store.db_path) as conn:
        conn.execute("UPDATE review_items SET status = 'approved_pending_enqueue' WHERE item_id = ?", (item_id,))

    # Second submission -> reuses existing outbox row without conflict error
    second_item = submission_svc.submit_approved_item(item_id)
    assert second_item is not None
    second_outbox = outbox.get_by_task_id(item_id)
    assert second_outbox is not None
    assert second_outbox["idempotency_key"] == first_idempotency_key


def test_worker_hmac_header_construction() -> None:
    """Verifies that OutboundWorkerV2 creates valid HMAC headers containing timestamp, nonce, signature, and key_id."""
    worker = OutboundWorkerV2(
        edge_base_url="https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1",
        worker_bearer_token="secret-bearer-123",
        worker_hmac_secret="secret-hmac-456",
        worker_id="worker-unit-1",
    )

    headers = worker._make_headers("POST", "/cvn-claim-outbound-item", '{"test":1}')

    assert headers["Authorization"] == "Bearer secret-bearer-123"
    assert headers["X-CVN-Key-Id"] == "worker-unit-1"
    assert "X-CVN-Signature" in headers
    assert len(headers["X-CVN-Signature"]) == 64
    assert "X-CVN-Timestamp" in headers
    assert "X-CVN-Nonce" in headers


def test_worker_5_element_hmac_canonical_calculation() -> None:
    """Verifies exact 5-element HMAC signature computation METHOD|PATH|TIMESTAMP|NONCE|BODY."""
    import hashlib
    import hmac

    worker = OutboundWorkerV2(
        edge_base_url="https://test.supabase.co/functions/v1",
        worker_bearer_token="secret-bearer-123",
        worker_hmac_secret="secret-hmac-456",
        worker_id="worker-unit-1",
    )

    path = "/cvn-claim-outbound-item"
    body = '{"test":1}'
    headers = worker._make_headers("POST", path, body)

    ts = headers["X-CVN-Timestamp"]
    nonce = headers["X-CVN-Nonce"]
    expected_canonical = f"POST|{path}|{ts}|{nonce}|{body}"
    expected_sig = hmac.new(
        b"secret-hmac-456",
        expected_canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert headers["X-CVN-Signature"] == expected_sig


def test_worker_process_item_return_status() -> None:
    """Verifies process_item returns False when completion HTTP request fails."""
    worker = OutboundWorkerV2(
        edge_base_url="https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1",
        worker_bearer_token="secret-bearer-123",
        worker_hmac_secret="secret-hmac-456",
        worker_id="worker-unit-1",
    )

    mock_claim = {
        "claimed": True,
        "item_id": "CVNI-20260802-180000-FAIL",
        "lease_token": "test_mock_lease_token_12345",
        "payload_hash": "a" * 64,
        "content_hash": "b" * 64,
        "target_agent": "openclaw",
    }

    mock_resp_fail = MagicMock()
    mock_resp_fail.read.return_value = json.dumps({"error": "unauthorized", "message": "Invalid signature"}).encode("utf-8")
    mock_resp_fail.__enter__.return_value = mock_resp_fail

    with patch("urllib.request.urlopen", return_value=mock_resp_fail):
        result = worker.process_item(mock_claim)
        assert result is False
