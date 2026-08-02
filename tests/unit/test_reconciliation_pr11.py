"""Unit test verifying PR 11 state reconciliation and idempotent mark_sent in OutboundReviewStore."""

from pathlib import Path
from app.destinations.outbound_review_store import OutboundReviewStore


def test_outbound_review_store_idempotent_mark_sent(tmp_path: Path) -> None:
    db_file = tmp_path / "test_review.db"
    store = OutboundReviewStore(db_path=db_file)

    item = store.create_review_item(
        item_id="CVNI-20260801-111111-TEST",
        note_path="notes/test.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json='{"content":{"title":"Test Title"}}',
        assessment_json='{"risk_level":"low"}',
    )
    assert item["status"] == "awaiting_review"

    approved = store.approve(item_id="CVNI-20260801-111111-TEST")
    assert approved["status"] == "approved_pending_enqueue"

    queued = store.mark_queued(item_id="CVNI-20260801-111111-TEST", outbox_local_id=1)
    assert queued["status"] == "queued"

    sent1 = store.mark_sent(item_id="CVNI-20260801-111111-TEST")
    assert sent1["status"] == "sent"

    # Repeated mark_sent call must be idempotent and return existing item without error
    sent2 = store.mark_sent(item_id="CVNI-20260801-111111-TEST")
    assert sent2["status"] == "sent"
