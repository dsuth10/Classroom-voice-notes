"""Unit tests for RecordDatabase."""

from pathlib import Path
import pytest
import sqlite3

from app.destinations.outbound_payload_builder import build_outbound_payload_v2
from app.destinations.record_db import IdempotencyConflictError, RecordDatabase, validate_payload_v2


@pytest.fixture
def temp_db(tmp_path: Path) -> RecordDatabase:
    db_file = tmp_path / "test_outbound_records.db"
    return RecordDatabase(db_file)


def _make_valid_v2_payload(
    item_id: str = "CVNI-REC-100",
    title: str = "Fractions Unit",
    recorded_at: str = "2026-08-03T09:00:00Z",
    duration_seconds: float = 120.0,
) -> dict:
    content = {
        "title": title,
        "category": "maths",
        "summary": "Equivalent fractions summary",
        "tags": ["maths", "year5"],
        "structured_fields": {"grade": "5", "unit": "3"},
        "recorded_at": recorded_at,
        "duration_seconds": duration_seconds,
        "transcript": "Today we explored equivalent fractions using visual bars.",
    }
    payload, _, content_hash = build_outbound_payload_v2(
        item_id=item_id,
        source_device_id="dev-alpha-123",
        item_kind="record_only",
        target_agent="openclaw",
        content=content,
        automatic_classification="confidential",
        risk_level="low",
        release_basis="human_approval",
        approval_metadata={"reviewer_type": "teacher_user"},
    )
    return payload


def test_init_db_creates_schema_v2(temp_db: RecordDatabase) -> None:
    assert temp_db.db_path.exists()
    with sqlite3.connect(temp_db.db_path) as conn:
        cursor = conn.execute("SELECT MAX(version) FROM schema_migrations")
        assert cursor.fetchone()[0] == 2


def test_upgrade_from_schema_v1_to_v2(tmp_path: Path) -> None:
    """Existing schema v1 database upgrades seamlessly to v2 while preserving records."""
    db_path = tmp_path / "legacy_v1_records.db"

    # 1. Create a legacy v1 database manually
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        conn.execute(
            """
            CREATE TABLE outbound_records (
                item_id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                source_device TEXT,
                created_at TEXT NOT NULL,
                recorded_at TEXT,
                received_at TEXT,
                completed_at TEXT NOT NULL DEFAULT (datetime('now')),
                duration_seconds REAL,
                title TEXT NOT NULL,
                summary TEXT,
                category TEXT,
                tags_json TEXT,
                structured_fields_json TEXT,
                transcript TEXT,
                classification TEXT,
                risk_level TEXT,
                release_basis TEXT,
                approval_metadata_json TEXT,
                safe_processing_ref TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO outbound_records (
                item_id, content_hash, schema_version, source_device, created_at, title
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("CVNI-LEGACY-001", "hash_v1", "cvn.outbound_item.v2", "dev-v1-device", "2026-08-01T12:00:00Z", "Legacy Note")
        )
        conn.commit()

    # 2. Instantiate RecordDatabase which executes v1 -> v2 migration
    db = RecordDatabase(db_path)

    # 3. Assert version 2 recorded in schema_migrations
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT MAX(version) FROM schema_migrations")
        assert cursor.fetchone()[0] == 2

        # Assert column source_device_id exists and source_device is renamed/copied
        cursor = conn.execute("PRAGMA table_info(outbound_records)")
        cols = [c[1] for c in cursor.fetchall()]
        assert "source_device_id" in cols
        assert "export_status" in cols

    # 4. Verify existing record preserved and accessible
    rec = db.get_record("CVNI-LEGACY-001")
    assert rec is not None
    assert rec["item_id"] == "CVNI-LEGACY-001"
    assert rec["title"] == "Legacy Note"
    assert rec["source_device_id"] == "dev-v1-device"

    # 5. Insert new v2 record into upgraded DB succeeds
    payload = _make_valid_v2_payload("CVNI-NEW-002")
    db.insert_record(payload)
    new_rec = db.get_record("CVNI-NEW-002")
    assert new_rec is not None
    assert new_rec["source_device_id"] == "dev-alpha-123"


def test_insert_record_success_maps_v2_contract(temp_db: RecordDatabase) -> None:
    payload = _make_valid_v2_payload()

    rec, is_new = temp_db.insert_record(payload)
    assert is_new is True
    assert rec["item_id"] == "CVNI-REC-100"
    assert rec["title"] == "Fractions Unit"
    assert rec["category"] == "maths"
    assert rec["source_device_id"] == "dev-alpha-123"
    assert rec["recorded_at"] == "2026-08-03T09:00:00Z"
    assert rec["duration_seconds"] == 120.0
    assert rec["classification"] == "confidential"
    assert rec["release_basis"] == "human_approval"
    assert "teacher_user" in rec["approval_metadata_json"]
    assert rec["transcript"] == "Today we explored equivalent fractions using visual bars."
    assert rec["export_status"] == "pending"


def test_recomputes_content_hash_and_rejects_caller_mismatch(temp_db: RecordDatabase) -> None:
    payload = _make_valid_v2_payload()

    # Tamper with content while keeping original content_hash
    payload["content"]["title"] = "Tampered Title"

    with pytest.raises(ValueError, match="does not match recomputed canonical content hash"):
        temp_db.insert_record(payload)


def test_strict_payload_validation(temp_db: RecordDatabase) -> None:
    # Missing schema_version
    p1 = _make_valid_v2_payload()
    p1["schema_version"] = "cvn.outbound_item.v1"
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        temp_db.insert_record(p1)

    # Empty title
    p2 = _make_valid_v2_payload()
    p2["content"]["title"] = ""
    with pytest.raises(ValueError, match="content.title must be a non-empty string"):
        temp_db.insert_record(p2)

    # Invalid item_kind
    p3 = _make_valid_v2_payload()
    p3["item_kind"] = "agent_task"
    with pytest.raises(ValueError, match="Expected 'record_only'"):
        temp_db.insert_record(p3)

    # Missing target_agent
    p4 = _make_valid_v2_payload()
    p4["target_agent"] = ""
    with pytest.raises(ValueError, match="missing valid non-empty target_agent"):
        temp_db.insert_record(p4)

    # Invalid created_at ISO timestamp
    p6 = _make_valid_v2_payload()
    p6["created_at"] = "invalid-timestamp"
    with pytest.raises(ValueError, match="is not a valid ISO 8601 timestamp"):
        temp_db.insert_record(p6)


def test_idempotent_duplicate_insert_returns_existing(temp_db: RecordDatabase) -> None:
    payload = _make_valid_v2_payload("CVNI-REC-101")

    rec1, is_new1 = temp_db.insert_record(payload)
    assert is_new1 is True

    rec2, is_new2 = temp_db.insert_record(payload)
    assert is_new2 is False
    assert rec1["item_id"] == rec2["item_id"]
    assert rec1["content_hash"] == rec2["content_hash"]


def test_conflicting_hash_raises_error(temp_db: RecordDatabase) -> None:
    p1 = _make_valid_v2_payload("CVNI-REC-102", title="Original Title")
    p2 = _make_valid_v2_payload("CVNI-REC-102", title="Conflicting Title")

    temp_db.insert_record(p1)

    with pytest.raises(IdempotencyConflictError, match="different content hash"):
        temp_db.insert_record(p2)
