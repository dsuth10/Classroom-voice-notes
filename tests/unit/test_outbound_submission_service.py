"""Unit tests for OutboundSubmissionService and Outbox Integration (Step 4 fail-closed and idempotency)."""

import json
from pathlib import Path
from unittest import mock
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
    config_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        settings = SettingsManager()
        settings.set("external_agent.source_device_id", "cvn-device-test12345")
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
        assessment_json=json.dumps({
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "findings": [],
            "checks_passed": ["valid_item_kind"],
        }),
    )

    # Approve item -> state approved_pending_enqueue
    c_hash = compute_content_hash("record_only", "openclaw", draft["content"], None)
    review_store.approve("CVNI-SUBMIT-1", "manual_ui", approved_content_hash=c_hash)
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
    c_hash = compute_content_hash("record_only", "openclaw", draft["content"], None)
    review_store.create_review_item(
        item_id="CVNI-HASH-1",
        note_path="/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
        }),
    )
    review_store.approve("CVNI-HASH-1", "manual_ui", approved_content_hash=c_hash)

    # Manually tamper with draft_json without updating approved_content_hash
    import sqlite3
    tampered_draft = json.dumps({"content": {"title": "Tampered Title"}})
    with sqlite3.connect(review_store.db_path) as conn:
        conn.execute(
            "UPDATE review_items SET draft_json = ? WHERE item_id = ?",
            (tampered_draft, "CVNI-HASH-1"),
        )
        conn.commit()

    with pytest.raises(ValueError, match="ERR_CONTENT_HASH_MISMATCH"):
        service.submit_approved_item("CVNI-HASH-1")

    item = review_store.get_by_id("CVNI-HASH-1")
    assert item["status"] == "enqueue_failed"
    assert "ERR_CONTENT_HASH_MISMATCH" in item["last_error"]


def test_submit_missing_approval_hash_fails(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    draft = {"content": {"title": "No Approval Hash"}}
    review_store.create_review_item(
        item_id="CVNI-NO-HASH",
        note_path="/notes/nohash.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"automatic_classification": "non_sensitive", "risk_level": "low"}),
        status="approved_pending_enqueue",
    )

    with pytest.raises(ValueError, match="ERR_MISSING_APPROVAL_HASH"):
        service.submit_approved_item("CVNI-NO-HASH")


def test_submit_missing_device_id_fails(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    settings.set("external_agent.source_device_id", "")
    draft = {"content": {"title": "Missing Device"}}
    c_hash = compute_content_hash("record_only", "openclaw", draft["content"], None)

    review_store.create_review_item(
        item_id="CVNI-NO-DEV",
        note_path="/notes/nodev.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"automatic_classification": "non_sensitive", "risk_level": "low"}),
    )
    review_store.approve("CVNI-NO-DEV", "manual_ui", approved_content_hash=c_hash)

    with pytest.raises(ValueError, match="ERR_MISSING_DEVICE_ID"):
        service.submit_approved_item("CVNI-NO-DEV")


def test_submit_outbox_exact_reuse_and_conflict_handling(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    draft = {"content": {"title": "Idempotent Submission"}}
    c_hash = compute_content_hash("record_only", "openclaw", draft["content"], None)

    review_store.create_review_item(
        item_id="CVNI-IDEM-1",
        note_path="/notes/idem.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"automatic_classification": "non_sensitive", "risk_level": "low"}),
    )
    review_store.approve("CVNI-IDEM-1", "manual_ui", approved_content_hash=c_hash)

    # First submit -> creates outbox row
    service.submit_approved_item("CVNI-IDEM-1")
    outbox_row1 = outbox.get_by_task_id("CVNI-IDEM-1")
    assert outbox_row1 is not None

    # Reset status back to approved_pending_enqueue to test re-enqueue idempotency
    import sqlite3
    with sqlite3.connect(review_store.db_path) as conn:
        conn.execute("UPDATE review_items SET status = 'approved_pending_enqueue' WHERE item_id = 'CVNI-IDEM-1'")
        conn.commit()

    # Second submit -> reuses exact outbox row without throwing or duplicating
    res2 = service.submit_approved_item("CVNI-IDEM-1")
    assert res2["outbox_local_id"] == outbox_row1["local_id"]


def test_submit_outbox_conflict_fails(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    draft = {"content": {"title": "Conflict Test"}}
    c_hash = compute_content_hash("record_only", "openclaw", draft["content"], None)

    review_store.create_review_item(
        item_id="CVNI-CONF-1",
        note_path="/notes/conf.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"automatic_classification": "non_sensitive", "risk_level": "low"}),
    )
    review_store.approve("CVNI-CONF-1", "manual_ui", approved_content_hash=c_hash)

    # Pre-populate outbox with a conflicting content_hash for the same item_id
    outbox.enqueue(
        task_id="CVNI-CONF-1",
        endpoint_url="https://test.supabase.co/functions/v1/cvn-submit-outbound-item",
        payload_json="{}",
        payload_hash="diff_hash",
        idempotency_key="key-1",
        nonce="nonce-1",
        schema_version="cvn.outbound_item.v2",
        item_kind="record_only",
        content_hash="CONFLICTING_HASH_12345",
        release_basis="human_approval",
    )

    with pytest.raises(ValueError, match="ERR_OUTBOX_CONFLICT"):
        service.submit_approved_item("CVNI-CONF-1")

    item = review_store.get_by_id("CVNI-CONF-1")
    assert item["status"] == "enqueue_failed"
    assert "ERR_OUTBOX_CONFLICT" in item["last_error"]


def test_reconcile_pending_enqueues(temp_env) -> None:
    settings, review_store, outbox, service = temp_env

    draft = {"content": {"title": "Rec item"}}
    c_hash = compute_content_hash("record_only", "openclaw", draft["content"], None)
    review_store.create_review_item(
        item_id="CVNI-REC-1",
        note_path="/notes/rec.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps({"automatic_classification": "non_sensitive", "risk_level": "low"}),
    )
    review_store.approve("CVNI-REC-1", approved_content_hash=c_hash)

    # Item is in approved_pending_enqueue
    item = review_store.get_by_id("CVNI-REC-1")
    assert item["status"] == "approved_pending_enqueue"

    reconciled_count = service.reconcile_pending_enqueues()
    assert reconciled_count == 1

    item_after = review_store.get_by_id("CVNI-REC-1")
    assert item_after["status"] == "queued"
    assert outbox.get_by_task_id("CVNI-REC-1") is not None
