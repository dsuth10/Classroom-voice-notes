"""Unit tests for RecordDatabase."""

from pathlib import Path
import pytest
import sqlite3

from app.destinations.record_db import IdempotencyConflictError, RecordDatabase


@pytest.fixture
def temp_db(tmp_path: Path) -> RecordDatabase:
    db_file = tmp_path / "test_outbound_records.db"
    return RecordDatabase(db_file)


def test_init_db_creates_schema_v1(temp_db: RecordDatabase) -> None:
    assert temp_db.db_path.exists()
    with sqlite3.connect(temp_db.db_path) as conn:
        cursor = conn.execute("SELECT MAX(version) FROM schema_migrations")
        assert cursor.fetchone()[0] == 1


def test_insert_record_success(temp_db: RecordDatabase) -> None:
    payload = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-REC-100",
        "item_kind": "record_only",
        "created_at": "2026-08-03T10:00:00Z",
        "source_device": "device-alpha",
        "content": {
            "title": "Fractions Unit",
            "category": "maths",
            "summary": "Equivalent fractions summary",
            "tags": ["maths", "year5"],
            "structured_fields": {"grade": "5", "unit": "3"},
            "transcript": "Today we explored equivalent fractions using visual bars.",
        },
        "privacy": {
            "classification": "internal",
            "risk_level": "low",
            "release_basis": "human_approval",
        },
        "task": None,
    }

    rec, is_new = temp_db.insert_record(payload)
    assert is_new is True
    assert rec["item_id"] == "CVNI-REC-100"
    assert rec["title"] == "Fractions Unit"
    assert rec["category"] == "maths"
    assert rec["source_device"] == "device-alpha"
    assert rec["transcript"] == "Today we explored equivalent fractions using visual bars."
    assert "year5" in rec["tags_json"]


def test_idempotent_duplicate_insert_returns_existing(temp_db: RecordDatabase) -> None:
    payload = {
        "item_id": "CVNI-REC-101",
        "item_kind": "record_only",
        "content": {"title": "Spelling Test"},
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }

    rec1, is_new1 = temp_db.insert_record(payload)
    assert is_new1 is True

    rec2, is_new2 = temp_db.insert_record(payload)
    assert is_new2 is False
    assert rec1["item_id"] == rec2["item_id"]
    assert rec1["content_hash"] == rec2["content_hash"]


def test_conflicting_hash_raises_error(temp_db: RecordDatabase) -> None:
    payload1 = {
        "item_id": "CVNI-REC-102",
        "item_kind": "record_only",
        "content": {"title": "Version Original"},
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }

    payload2 = {
        "item_id": "CVNI-REC-102",
        "item_kind": "record_only",
        "content": {"title": "Version Mutated / Conflicting"},
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }

    temp_db.insert_record(payload1)

    with pytest.raises(IdempotencyConflictError, match="different content hash"):
        temp_db.insert_record(payload2)


def test_rejects_invalid_payloads(temp_db: RecordDatabase) -> None:
    with pytest.raises(ValueError, match="missing valid item_id"):
        temp_db.insert_record({"item_kind": "record_only"})

    with pytest.raises(ValueError, match="cannot process item_kind"):
        temp_db.insert_record({"item_id": "123", "item_kind": "agent_task"})

    with pytest.raises(ValueError, match="cannot contain task instructions"):
        temp_db.insert_record({
            "item_id": "123",
            "item_kind": "record_only",
            "task": {"instructions": "do work"},
        })


def test_transcript_excluded_if_not_in_content(temp_db: RecordDatabase) -> None:
    payload = {
        "item_id": "CVNI-REC-103",
        "item_kind": "record_only",
        "content": {"title": "No transcript note"},
        "task": None,
    }

    rec, _ = temp_db.insert_record(payload)
    assert rec["transcript"] is None
