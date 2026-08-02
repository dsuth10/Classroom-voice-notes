"""Unit tests for PR 9 transactional review store and CSV export functionality."""

import csv
import json
from pathlib import Path
import pytest

from app.destinations.outbound_review_store import OutboundReviewStore


def test_transactional_store_operations_and_csv_export(tmp_path: Path) -> None:
    """Verifies SQLite transactional integrity and CSV export functionality."""
    db_file = tmp_path / "test_store_pr9.db"
    csv_file = tmp_path / "exports" / "review_report.csv"

    store = OutboundReviewStore(db_file)

    # 1. Create items transactionally
    item1 = store.create_review_item(
        item_id="CVNI-PR9-1",
        note_path="/notes/lesson1.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Lesson 1"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
    )
    assert item1["status"] == "awaiting_review"

    # 2. Transition state transactionally
    store.approve("CVNI-PR9-1", approval_method="manual_ui")
    approved = store.get_by_id("CVNI-PR9-1")
    assert approved is not None
    assert approved["status"] == "approved_pending_enqueue"
    assert approved["approved_content_hash"] == approved["content_hash"]

    # 3. Export to CSV as read-only report
    count = store.export_to_csv(csv_file)
    assert count == 1
    assert csv_file.exists()

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["item_id"] == "CVNI-PR9-1"
        assert rows[0]["status"] == "approved_pending_enqueue"
