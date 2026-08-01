"""Unit tests for OutboundSubmissionService and Outbox Integration."""

import json
from pathlib import Path
import pytest

from app.config.settings import SettingsManager
from app.destinations.external_outbox import ExternalOutbox
from app.destinations.outbound_review_store import (
    OutboundReviewStore,
    compute_content_hash,
)
from app.destinations.outbound_submission_service import OutboundSubmissionService


@pytest.fixture
def temp_env(tmp_path: Path):
    settings = SettingsManager()
    review_store = OutboundReviewStore(tmp_path / "review.db")
    outbox = ExternalOutbox(tmp_path / "outbox.db")
    service = OutboundSubmissionService(
        settings_manager=settings, review_store=review_store, outbox=outbox
    )
    return settings, review_store, outbox, service


def test_submit_approved_item_success(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    draft = {
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {"title": "Fractions Intro", "summary": "Maths lesson"},
        "task": None,
    }
    review_store.create_review_item(
        item_id="CVNI-SUBMIT-1",
        note_path="/notes/maths.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"risk_level": "low", "findings": []}),
    )

    # Approve item -> state approved_pending_enqueue
    review_store.approve("CVNI-SUBMIT-1", "manual_ui")
    approved = review_store.get_by_id("CVNI-SUBMIT-1")
    assert approved["status"] == "approved_pending_enqueue"

    # Submit to outbox
    submitted = service.submit_approved_item("CVNI-SUBMIT-1")
    assert submitted["status"] == "queued"
    assert submitted["outbox_local_id"] is not None

    # Check outbox record
    outbox_item = outbox.get_by_task_id("CVNI-SUBMIT-1")
    assert outbox_item is not None
    assert outbox_item["status"] == "pending"
    assert outbox_item["target_agent"] == "openclaw"
    payload = json.loads(outbox_item["payload_json"])
    assert payload["schema_version"] == "cvn.outbound_item.v2"
    assert payload["item_id"] == "CVNI-SUBMIT-1"


def test_submit_item_hash_mismatch_fails(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    draft = {
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {"title": "Original Title"},
    }
    review_store.create_review_item(
        item_id="CVNI-HASH-1",
        note_path="/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"risk_level": "low"}),
    )
    review_store.approve("CVNI-HASH-1", "manual_ui")

    # Manually tamper with draft_json without updating approved_content_hash
    import sqlite3
    tampered_draft = json.dumps({"content": {"title": "Tampered Title"}})
    with sqlite3.connect(review_store.db_path) as conn:
        conn.execute(
            "UPDATE review_items SET draft_json = ? WHERE item_id = ?",
            (tampered_draft, "CVNI-HASH-1"),
        )
        conn.commit()

    with pytest.raises(ValueError, match="Content hash mismatch"):
        service.submit_approved_item("CVNI-HASH-1")

    item = review_store.get_by_id("CVNI-HASH-1")
    assert item["status"] == "enqueue_failed"
    assert "Content hash mismatch" in item["last_error"]


def test_reconcile_pending_enqueues(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    review_store.create_review_item(
        item_id="CVNI-REC-1",
        note_path="/notes/rec.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Rec item"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )
    review_store.approve("CVNI-REC-1")

    # Item is in approved_pending_enqueue
    item = review_store.get_by_id("CVNI-REC-1")
    assert item["status"] == "approved_pending_enqueue"

    reconciled_count = service.reconcile_pending_enqueues()
    assert reconciled_count == 1

    item_after = review_store.get_by_id("CVNI-REC-1")
    assert item_after["status"] == "queued"
    assert outbox.get_by_task_id("CVNI-REC-1") is not None
