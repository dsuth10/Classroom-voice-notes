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


def test_update_draft_recalculates_hash_and_resets_approval(
    temp_store: OutboundReviewStore,
) -> None:
    draft1 = {"content": {"title": "Original Title"}}
    item = temp_store.create_review_item(
        item_id="CVNI-001",
        note_path="/vault/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps(draft1),
        assessment_json=json.dumps({"risk_level": "low"}),
    )
    hash1 = item["content_hash"]

    # Approve item first
    approved_item = temp_store.approve(
        "CVNI-001", approval_method="manual_ui"
    )
    assert approved_item["status"] == "approved"
    assert approved_item["approved_at"] is not None

    # Now update draft -> Hash changes and approval resets
    draft2 = {"content": {"title": "Edited Title"}}
    updated_item = temp_store.update_draft("CVNI-001", draft2)

    assert updated_item["status"] == "awaiting_review"
    assert updated_item["approved_at"] is None
    assert updated_item["approval_method"] is None
    assert updated_item["content_hash"] != hash1


def test_approve_reject_flow(temp_store: OutboundReviewStore) -> None:
    temp_store.create_review_item(
        item_id="CVNI-001",
        note_path="/vault/notes/1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Note"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )

    app_item = temp_store.approve("CVNI-001", "manual_ui")
    assert app_item["status"] == "approved"
    assert app_item["approval_method"] == "manual_ui"

    rej_item = temp_store.reject("CVNI-001", "Contains private note")
    assert rej_item["status"] == "rejected"
    assert rej_item["rejection_reason"] == "Contains private note"


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
    assert stats.get("approved") == 1


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
