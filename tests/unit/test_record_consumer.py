"""Unit tests for RecordConsumer."""
from pathlib import Path
import pytest
from app.destinations.record_consumer import RecordConsumer


@pytest.fixture
def temp_consumer(tmp_path: Path) -> RecordConsumer:
    export_csv = tmp_path / "outbound_records.csv"
    return RecordConsumer(export_csv)


def test_process_record_success(temp_consumer: RecordConsumer) -> None:
    payload = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-REC-001",
        "created_at": "2026-08-01T12:00:00Z",
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {
            "title": "Fractions Lesson Reflection",
            "category": "maths_note",
            "summary": "Taught fraction division",
            "tags": ["maths", "fractions"],
            "structured_fields": {"unit": "5B"},
        },
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }

    res = temp_consumer.process_record(payload)
    assert res["status"] == "exported"
    assert res["item_id"] == "CVNI-REC-001"
    assert temp_consumer.is_already_processed("CVNI-REC-001") is True

    # Duplicate call -> skips idempotently
    res_dup = temp_consumer.process_record(payload)
    assert res_dup["status"] == "duplicate_skipped"


def test_process_record_rejects_agent_task_kind(
    temp_consumer: RecordConsumer,
) -> None:
    payload = {
        "item_id": "CVNI-REC-002",
        "item_kind": "agent_task",
        "content": {"title": "Task"},
        "task": {"title": "Task", "instructions": "Do something"},
    }
    with pytest.raises(ValueError, match="cannot process item_kind"):
        temp_consumer.process_record(payload)


def test_process_record_rejects_task_in_record_only(
    temp_consumer: RecordConsumer,
) -> None:
    payload = {
        "item_id": "CVNI-REC-003",
        "item_kind": "record_only",
        "content": {"title": "Note"},
        "task": {"title": "Sneaky Task", "instructions": "Execute code"},
    }
    with pytest.raises(ValueError, match="cannot contain task instructions"):
        temp_consumer.process_record(payload)
