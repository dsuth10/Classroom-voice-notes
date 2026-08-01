"""End-to-End Integration Test for Outbound Sharing Remediation (PR 10)."""

import csv
import json
from pathlib import Path
import pytest

from app.config.settings import SettingsManager
from app.destinations.external_outbox import ExternalOutbox
from app.destinations.outbound_review_store import OutboundReviewStore
from app.destinations.outbound_routing_service import OutboundRoutingService
from app.destinations.outbound_submission_service import OutboundSubmissionService
from app.destinations.record_consumer import RecordConsumer


def test_full_outbound_sharing_e2e_flow(tmp_path: Path) -> None:
    # 1. Setup isolated stores and settings
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "review_all")

    review_store = OutboundReviewStore(tmp_path / "review.db")
    outbox = ExternalOutbox(tmp_path / "outbox.db")
    submission_service = OutboundSubmissionService(
        settings_manager=settings, review_store=review_store, outbox=outbox
    )
    export_csv = tmp_path / "export_records.csv"
    record_consumer = RecordConsumer(export_file=export_csv)

    # 2. Voice capture & classification routing
    note_path = tmp_path / "class_note.md"
    note_path.write_text("# Year 5 Fractions Lesson", encoding="utf-8")

    routing_service = OutboundRoutingService(settings, review_store=review_store)
    route_result = routing_service.handle_capture(
        classification={
            "category": "general_note",
            "sensitivity": "non_sensitive",
            "title": "=SUM(1+1) Fractions Lesson",
            "summary": "Introduction to adding fractions",
            "category_fields": {"unit": "Maths"},
        },
        transcript="Class completed page 42.",
        note_path=str(note_path),
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=45,
    )

    item_id = route_result.item_id
    assert item_id is not None
    assert route_result.action == "added_to_review_queue"

    # 3. Verify item created in review_store with status awaiting_review
    review_item = review_store.get_by_id(item_id)
    assert review_item is not None
    assert review_item["status"] == "awaiting_review"
    assert review_item["item_kind"] == "record_only"

    # 4. User edits draft in review dialog
    draft = json.loads(review_item["draft_json"])
    draft["content"]["summary"] = "=Edited summary intro"
    updated = review_store.update_draft(item_id, draft)
    assert updated is not None
    assert updated["status"] == "awaiting_review"

    # 5. User approves item in review UI -> approved_pending_enqueue
    approved = review_store.approve(item_id, approval_method="manual_ui")
    assert approved is not None
    assert approved["status"] == "approved_pending_enqueue"
    assert approved["approved_content_hash"] == approved["content_hash"]

    # 6. Submission service enqueues payload to durable outbox
    submitted = submission_service.submit_approved_item(item_id)
    assert submitted is not None
    assert submitted["status"] == "queued"
    assert submitted["outbox_local_id"] is not None

    # 7. Verify outbox payload schema v2 and parameters
    outbox_entry = outbox.get_by_task_id(item_id)
    assert outbox_entry is not None
    assert outbox_entry["status"] == "pending"

    payload = json.loads(outbox_entry["payload_json"])
    assert payload["schema_version"] == "cvn.outbound_item.v2"
    assert payload["item_id"] == item_id
    assert payload["privacy"]["release_basis"] == "human_approval"
    assert payload["privacy"]["approval"]["approved_content_hash"] == payload["content_hash"]

    # 8. Worker / RecordConsumer processes item from outbox
    consumer_result = record_consumer.process_record(payload)
    assert consumer_result["status"] == "exported"

    # 9. Verify exported CSV is sanitized against formula injection
    with open(export_csv, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 2
    data_row = rows[1]
    # title '=SUM(1+1) Fractions Lesson' was prefixed with single quote
    assert data_row[2] == "'=SUM(1+1) Fractions Lesson"
    # summary '=Edited summary intro' was prefixed with single quote
    assert data_row[4] == "'=Edited summary intro"
