"""Unit tests for RecordConsumer and generated CSV export."""

import csv as _csv
import json as _json
from pathlib import Path
import pytest
from app.destinations.record_consumer import RecordConsumer, sanitize_csv_field
from app.destinations.record_db import IdempotencyConflictError


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


def _make_payload(item_id: str = "CVNI-20260801-120000-AA01") -> dict:
    return {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "item_kind": "record_only",
        "created_at": "2026-08-01T12:00:00Z",
        "content": {
            "title": "Maths",
            "category": "general_note",
            "summary": "Fractions",
            "tags": ["year5", "maths"],
            "structured_fields": {"b": "2", "a": "1"},
        },
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }


def test_sqlite_idempotency_one_csv_row(tmp_path: Path) -> None:
    """Duplicate delivery produces exactly one CSV data row."""
    export_file = tmp_path / "records.csv"
    consumer = RecordConsumer(export_file=export_file)
    payload = _make_payload()
    res1 = consumer.process_record(payload)
    res2 = consumer.process_record(payload)
    assert res1["status"] == "exported"
    assert res2["status"] == "duplicate_skipped"
    with open(export_file, "r", encoding="utf-8") as f:
        rows = list(_csv.reader(f))
    assert len(rows) == 2  # header + exactly 1 data row


def test_formula_injection_sanitization() -> None:
    """Dangerous formula prefixes are escaped with a single quote."""
    assert sanitize_csv_field("=HYPERLINK('x','y')").startswith("'")
    assert sanitize_csv_field("+1-2").startswith("'")
    assert sanitize_csv_field("-DROP TABLE").startswith("'")
    assert sanitize_csv_field("@A1").startswith("'")
    assert sanitize_csv_field("Normal text") == "Normal text"
    assert sanitize_csv_field(None) == ""


def test_structured_fields_sorted_in_csv(tmp_path: Path) -> None:
    """Structured fields keys are sorted in the CSV output."""
    export_file = tmp_path / "records.csv"
    consumer = RecordConsumer(export_file=export_file)
    payload = _make_payload("CVNI-20260801-120000-BB01")
    consumer.process_record(payload)
    with open(export_file, "r", encoding="utf-8") as f:
        rows = list(_csv.reader(f))
    sf = _json.loads(rows[1][6])
    assert list(sf.keys()) == sorted(sf.keys())


def test_conflicting_payload_raises_permanent_error(tmp_path: Path) -> None:
    """Same item ID with different content hash raises IdempotencyConflictError."""
    export_file = tmp_path / "records.csv"
    consumer = RecordConsumer(export_file=export_file)
    p1 = _make_payload("CVNI-CONFLICT-01")
    p2 = _make_payload("CVNI-CONFLICT-01")
    p2["content"]["title"] = "Different Title"

    consumer.process_record(p1)
    with pytest.raises(IdempotencyConflictError):
        consumer.process_record(p2)


def test_multiline_unicode_csv_roundtrip(tmp_path: Path) -> None:
    """Multiline Unicode text roundtrips safely through CSV generation."""
    export_file = tmp_path / "records.csv"
    consumer = RecordConsumer(export_file=export_file)
    unicode_title = "Year 5 — English Lesson: ✨ Multi-line Title \n Line 2 with commas, quotes \"hello\" and emoji 🚀"
    payload = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-UNICODE-01",
        "item_kind": "record_only",
        "created_at": "2026-08-03T12:00:00Z",
        "content": {
            "title": unicode_title,
            "category": "english",
            "summary": "Summary text",
            "tags": ["english", "year5"],
            "structured_fields": {"key": "val"},
        },
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }

    res = consumer.process_record(payload)
    assert res["status"] == "exported"

    with open(export_file, "r", encoding="utf-8") as f:
        rows = list(_csv.reader(f))

    assert len(rows) == 2
    assert rows[1][2] == unicode_title


def test_export_failure_does_not_undo_db_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Export generation failure logged; SQLite record remains committed."""
    export_file = tmp_path / "records.csv"
    consumer = RecordConsumer(export_file=export_file)

    def mock_bad_export(self_obj: RecordConsumer) -> Path:
        raise OSError("Simulated disk full during CSV export")

    monkeypatch.setattr(RecordConsumer, "regenerate_csv", mock_bad_export)

    payload = _make_payload("CVNI-FAIL-EXPORT-01")
    res = consumer.process_record(payload)

    assert res["status"] == "exported"
    assert consumer.is_already_processed("CVNI-FAIL-EXPORT-01") is True
