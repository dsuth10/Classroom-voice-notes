"""Unit tests for Step 8 concurrency, process locking, and crash failure scenarios."""

from concurrent.futures import ThreadPoolExecutor
import csv
from multiprocessing import Process
from pathlib import Path
import pytest
import sqlite3

from app.destinations.outbound_payload_builder import build_outbound_payload_v2
from app.destinations.record_consumer import RecordConsumer
from app.destinations.record_db import RecordDatabase


def _make_payload(item_id: str, title: str = "Test Title") -> dict:
    content = {
        "title": title,
        "category": "maths",
        "summary": "Summary text",
        "tags": ["maths", "year5"],
        "structured_fields": {"key": "val"},
        "recorded_at": "2026-08-03T10:00:00Z",
        "duration_seconds": 30.0,
    }
    payload, _, _ = build_outbound_payload_v2(
        item_id=item_id,
        source_device_id="dev-proc-01",
        item_kind="record_only",
        target_agent="openclaw",
        content=content,
        automatic_classification="non_sensitive",
        release_basis="human_approval",
    )
    return payload


def test_crash_before_commit_permits_retry(tmp_path: Path) -> None:
    """Crash before SQLite commit leaves no record and permits full retry."""
    db_file = tmp_path / "crash_test.db"
    db = RecordDatabase(db_file)
    payload = _make_payload("CVNI-CRASH-01")

    # Simulate an error/crash during transaction before commit
    with pytest.raises(RuntimeError):
        with sqlite3.connect(db_file) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO outbound_records (item_id, content_hash, schema_version, title, created_at) VALUES (?, ?, ?, ?, ?)",
                ("CVNI-CRASH-01", "hash1", "cvn.outbound_item.v2", "Title", "2026-08-03T10:00:00Z")
            )
            # Simulated process crash before conn.commit()
            raise RuntimeError("Process crashed before transaction commit!")

    # Verify no record exists in database
    assert db.get_record("CVNI-CRASH-01") is None

    # Retry succeeds cleanly
    rec, is_new = db.insert_record(payload)
    assert is_new is True
    assert rec["item_id"] == "CVNI-CRASH-01"


def test_crash_after_commit_returns_idempotent_success(tmp_path: Path) -> None:
    """Crash after SQLite commit returns duplicate_skipped / idempotent success on redelivery."""
    export_file = tmp_path / "outbound_records.csv"
    consumer = RecordConsumer(export_file=export_file)
    payload = _make_payload("CVNI-CRASH-02")

    # Transaction succeeds in SQLite
    res1 = consumer.process_record(payload)
    assert res1["status"] == "exported"

    # Simulate worker crash after commit & redelivery of same payload
    res2 = consumer.process_record(payload)
    assert res2["status"] == "duplicate_skipped"
    assert consumer.is_already_processed("CVNI-CRASH-02") is True


def test_concurrent_unique_inserts(tmp_path: Path) -> None:
    """Concurrent unique record insertions all survive in SQLite database."""
    export_file = tmp_path / "outbound_records.csv"
    consumer = RecordConsumer(export_file=export_file)

    items_count = 20
    payloads = [_make_payload(f"CVNI-CONCUR-{i:03d}", f"Title {i}") for i in range(items_count)]

    def _insert_payload(p: dict) -> dict:
        return consumer.process_record(p)

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_insert_payload, payloads))

    assert len(results) == items_count
    for r in results:
        assert r["status"] == "exported"

    all_records = consumer.db.get_all_records()
    assert len(all_records) == items_count


def _worker_process_task(export_file_str: str, item_id: str, title: str) -> None:
    """Worker task executed in a separate process."""
    export_file = Path(export_file_str)
    consumer = RecordConsumer(export_file=export_file)
    p = _make_payload(item_id, title)
    consumer.process_record(p)


def test_concurrent_process_export(tmp_path: Path) -> None:
    """Multiple separate worker processes writing to CSV export with inter-process lock survive cleanly."""
    export_file = tmp_path / "multiproc_records.csv"

    processes = []
    process_count = 6
    for i in range(process_count):
        item_id = f"CVNI-PROC-{i:03d}"
        title = f"Multi-Process Title {i}"
        proc = Process(
            target=_worker_process_task,
            args=(str(export_file), item_id, title),
        )
        processes.append(proc)
        proc.start()

    for proc in processes:
        proc.join(timeout=10.0)

    # Verify CSV file exists and contains all records
    assert export_file.exists()
    with open(export_file, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    # 1 header + process_count data rows
    assert len(rows) == process_count + 1
