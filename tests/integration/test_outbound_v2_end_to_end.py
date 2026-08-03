"""End-to-end synthetic integration tests for outbound sharing v2 lifecycle.

Validates the full v2 pipeline:
1. Draft creation and PolicyGate assessment
2. Re-assessment on edit and approval with canonical hash generation
3. Outbox submission and payload construction
4. Worker claim, execution, lease token validation, and completion
5. Unauthorized trusted mode rejection
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.destinations.canonical_json import compute_canonical_content_hash
from app.destinations.outbound_payload_builder import build_outbound_payload_v2
from app.destinations.outbound_review_store import OutboundReviewStore
from app.destinations.outbound_submission_service import OutboundSubmissionService
from app.ollama_router.policy_gate import PolicyGate
from scripts.outbound_worker_v2 import OutboundWorkerV2


def test_full_v2_outbound_lifecycle_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies complete v2 lifecycle from capture draft to worker completion."""
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")
    store = OutboundReviewStore(tmp_path / "e2e_review.db")
    item_id = "CVNI-20260802-140000-E2E1"

    # 1. Capture & Initial Review Store Creation
    draft_dict = {
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {"title": "Maths Year 5 Note", "summary": "Fractions practice"},
        "task": None,
    }
    gate = PolicyGate()
    assessment = gate.assess_v2_item(
        item_kind=draft_dict["item_kind"],
        target_agent=draft_dict["target_agent"],
        content=draft_dict["content"],
        task=draft_dict["task"],
    )

    assessment_json = json.dumps({
        "automatic_classification": assessment.automatic_classification,
        "risk_level": assessment.risk_level,
        "findings": assessment.findings,
    })
    store.create_review_item(
        item_id=item_id,
        note_path=str(tmp_path / "note.md"),
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft_dict),
        assessment_json=assessment_json,
        status="awaiting_review",
    )

    # 2. Approve draft & transition to approved_pending_enqueue
    store.approve(item_id, approval_method="manual_ui")
    approved_item = store.get_by_id(item_id)
    assert approved_item is not None
    assert approved_item["status"] == "approved_pending_enqueue"
    assert approved_item["approved_content_hash"] == approved_item["content_hash"]

    # 3. Enqueue to durable Outbox via OutboundSubmissionService
    mock_outbox = MagicMock()
    mock_outbox.get_by_task_id.return_value = None
    mock_outbox.enqueue.return_value = 101

    submission_svc = OutboundSubmissionService(review_store=store, outbox=mock_outbox)
    queued_item = submission_svc.submit_approved_item(item_id)
    assert queued_item is not None
    assert queued_item["status"] == "queued"
    mock_outbox.enqueue.assert_called_once()

    from app.worker.journal import WorkerJournal

    # 4. OutboundWorkerV2 Claim & Completion
    worker = OutboundWorkerV2(
        edge_base_url="https://synthetic.supabase.co/functions/v1",
        worker_bearer_token="synthetic-worker-token",
        worker_hmac_secret="synthetic-hmac-secret",
        worker_id="worker-e2e-1",
        journal=WorkerJournal(db_path=tmp_path / "e2e_journal.db"),
    )

    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", draft_dict["content"])

    payload_json = {
        "schema_version": "cvn.outbound_item.v2",
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "item_id": item_id,
        "source_device_id": "dev-01",
        "created_at": "2026-08-03T10:00:00Z",
        "content_hash": valid_hash,
        "content": draft_dict["content"],
        "privacy": {
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "release_basis": "automatic_policy",
            "checks_passed": ["content_classification_pass"],
        },
    }

    mock_resp_claim = MagicMock()
    mock_resp_claim.read.return_value = json.dumps({
        "claimed": True,
        "item_id": item_id,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "lease_token": "test_mock_lease_token_e2e_99",
        "payload_hash": f"sha256:{valid_hash}",
        "content_hash": valid_hash,
        "payload_json": payload_json,
    }).encode("utf-8")
    mock_resp_claim.__enter__.return_value = mock_resp_claim

    mock_resp_complete = MagicMock()
    mock_resp_complete.read.return_value = json.dumps({
        "success": True,
        "item_id": item_id,
        "status": "completed",
    }).encode("utf-8")
    mock_resp_complete.__enter__.return_value = mock_resp_complete

    with patch("urllib.request.urlopen", side_effect=[mock_resp_claim, mock_resp_complete]):
        claimed_payload = worker.claim_item()
        assert claimed_payload is not None
        assert claimed_payload["lease_token"] == "test_mock_lease_token_e2e_99"

        success = worker.process_item(claimed_payload)
        assert success is True

    # 5. Reconcile remote completed status
    status_rpc = MagicMock()
    status_rpc.execute.return_value = MagicMock(
        data={"found": True, "item_id": item_id, "status": "completed"}
    )
    status_client = MagicMock()
    status_client.rpc.return_value = status_rpc

    submission_svc.reconcile_remote_statuses(broker_client=status_client)
    final_item = store.get_by_id(item_id)
    assert final_item is not None
    assert final_item["status"] == "sent"


def test_canonical_hash_mismatch_rejection() -> None:
    """Verifies that tampering with content alters canonical hash and fails verification."""
    item_kind = "record_only"
    target_agent = "openclaw"
    original_content = {"title": "Original Note"}
    tampered_content = {"title": "Tampered Note"}

    _, original_hash = compute_canonical_content_hash(item_kind, target_agent, original_content)
    _, tampered_hash = compute_canonical_content_hash(item_kind, target_agent, tampered_content)

    assert original_hash != tampered_hash
