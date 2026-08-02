"""Unit tests for OutboundReviewStore."""
import json
from pathlib import Path
import pytest
from app.destinations.outbound_review_store import (
    OutboundReviewStore,
    compute_content_hash,
)


@pytest.fixture
def temp_store(tmp_path: Path) -> OutboundReviewStore:
    db_file = tmp_path / "test_outbound_review.db"
    return OutboundReviewStore(db_file)


def test_create_and_get_by_id(temp_store: OutboundReviewStore) -> None:
    draft = {
        "content": {"title": "Maths lesson", "summary": "Fractions intro"},
        "task": None,
    }
    assessment = {"risk_level": "low", "findings": []}
    item = temp_store.create_review_item(
        item_id="CVNI-001",
        note_path="/vault/notes/maths.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft),
        assessment_json=json.dumps(assessment),
    )

    assert item is not None
    assert item["item_id"] == "CVNI-001"
    assert item["status"] == "awaiting_review"
    assert item["item_kind"] == "record_only"
    assert item["target_agent"] == "openclaw"
    assert len(item["content_hash"]) == 64  # SHA-256 hex string


def test_get_awaiting_review(temp_store: OutboundReviewStore) -> None:
    temp_store.create_review_item(
        item_id="CVNI-001",
        note_path="/vault/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Note 1"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )
    temp_store.create_review_item(
        item_id="CVNI-002",
        note_path="/vault/notes/2.md",
        item_kind="agent_task",
        target_agent="hermes",
        draft_json=json.dumps({"content": {"title": "Note 2"}}),
        assessment_json=json.dumps({"risk_level": "medium"}),
    )

    awaiting = temp_store.get_awaiting_review()
    assert len(awaiting) == 2


def test_update_draft_updates_columns_and_recalculates_hash(
    temp_store: OutboundReviewStore,
) -> None:
    draft1 = {"item_kind": "record_only", "target_agent": "openclaw", "content": {"title": "Original Title"}}
    item = temp_store.create_review_item(
        item_id="CVNI-001",
        note_path="/vault/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft1),
        assessment_json=json.dumps({"risk_level": "low"}),
    )
    hash1 = item["content_hash"]

    # Approve item -> status becomes approved_pending_enqueue
    approved_item = temp_store.approve("CVNI-001", approval_method="manual_ui")
    assert approved_item["status"] == "approved_pending_enqueue"
    assert approved_item["approved_at"] is not None
    assert approved_item["approved_content_hash"] == hash1

    # Editing an item in approved_pending_enqueue is disallowed
    draft2 = {"item_kind": "agent_task", "target_agent": "openclaw", "content": {"title": "Edited Title"}}
    with pytest.raises(ValueError, match="Illegal transition"):
        temp_store.update_draft("CVNI-001", draft2)


def test_allowed_state_machine_lifecycle(temp_store: OutboundReviewStore) -> None:
    temp_store.create_review_item(
        item_id="CVNI-FLOW-1",
        note_path="/vault/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Note"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    # 1. approve: awaiting_review -> approved_pending_enqueue
    item = temp_store.approve("CVNI-FLOW-1", "manual_ui")
    assert item["status"] == "approved_pending_enqueue"
    assert item["approved_content_hash"] == item["content_hash"]

    # 2. mark_queued: approved_pending_enqueue -> queued
    item = temp_store.mark_queued("CVNI-FLOW-1", outbox_local_id=101)
    assert item["status"] == "queued"
    assert item["queued_at"] is not None
    assert item["outbox_local_id"] == 101

    # 3. mark_delivery_failed: queued -> delivery_failed
    item = temp_store.mark_delivery_failed("CVNI-FLOW-1", "Network timeout")
    assert item["status"] == "delivery_failed"
    assert item["last_error"] == "Network timeout"
    assert item["retry_count"] == 1

    # 4. retry enqueue/dispatch: delivery_failed -> sent
    item = temp_store.mark_sent("CVNI-FLOW-1")
    assert item["status"] == "sent"
    assert item["sent_at"] is not None


def test_disallowed_state_transitions(temp_store: OutboundReviewStore) -> None:
    temp_store.create_review_item(
        item_id="CVNI-ILLEGAL-1",
        note_path="/vault/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Note"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    temp_store.approve("CVNI-ILLEGAL-1")
    temp_store.mark_queued("CVNI-ILLEGAL-1", outbox_local_id=1)

    # Disallow approving a queued item
    with pytest.raises(ValueError, match="Illegal transition"):
        temp_store.approve("CVNI-ILLEGAL-1")

    # Disallow rejecting a queued item
    with pytest.raises(ValueError, match="Illegal transition"):
        temp_store.reject("CVNI-ILLEGAL-1", "Should fail")

    # Mark sent
    temp_store.mark_sent("CVNI-ILLEGAL-1")

    # Disallow editing or rejecting a sent item
    with pytest.raises(ValueError, match="Illegal transition"):
        temp_store.update_draft("CVNI-ILLEGAL-1", {"content": {"title": "Changed"}})

    with pytest.raises(ValueError, match="Illegal transition"):
        temp_store.reject("CVNI-ILLEGAL-1", "Reject sent item")


def test_get_stats(temp_store: OutboundReviewStore) -> None:
    temp_store.create_review_item(
        item_id="CVNI-001",
        note_path="1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {}}),
        assessment_json=json.dumps({}),
    )
    temp_store.create_review_item(
        item_id="CVNI-002",
        note_path="2.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {}}),
        assessment_json=json.dumps({}),
    )
    temp_store.approve("CVNI-001")

    stats = temp_store.get_stats()
    assert stats.get("awaiting_review") == 1
    assert stats.get("approved_pending_enqueue") == 1


def test_purge_expired_reviews(temp_store: OutboundReviewStore) -> None:
    import sqlite3
    from datetime import datetime, timedelta, timezone

    temp_store.create_review_item(
        item_id="CVNI-OLD-001",
        note_path="old.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {}}),
        assessment_json=json.dumps({}),
    )
    temp_store.reject("CVNI-OLD-001", "Too old")

    old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with sqlite3.connect(temp_store.db_path) as conn:
        conn.execute(
            "UPDATE review_items SET updated_at = ? WHERE item_id = ?",
            (old_time, "CVNI-OLD-001"),
        )
        conn.commit()

    temp_store.create_review_item(
        item_id="CVNI-NEW-001",
        note_path="new.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {}}),
        assessment_json=json.dumps({}),
    )

    purged = temp_store.purge_expired_reviews(retention_days=30)
    assert purged == 1
    assert temp_store.get_by_id("CVNI-OLD-001") is None
    assert temp_store.get_by_id("CVNI-NEW-001") is not None

