"""Unit tests for WorkerJournal local SQLite store."""

import os
import time
from pathlib import Path
from app.worker.journal import WorkerJournal, get_journal_db_path


def test_journal_db_path_resolution(tmp_path: Path, monkeypatch) -> None:
    custom_path = tmp_path / "custom_journal.db"
    monkeypatch.setenv("CVN_WORKER_JOURNAL_PATH", str(custom_path))
    assert get_journal_db_path() == custom_path


def test_journal_crud_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "test_journal.db"
    journal = WorkerJournal(db_path=db_path)

    item_id = "test-item-001"
    payload_hash = "sha256:abc"
    content_hash = "sha256:def"

    entry = journal.record_claim(item_id, payload_hash, content_hash, "record_only")
    assert entry["item_id"] == item_id
    assert entry["state"] == "claimed"
    assert entry["consumer_kind"] == "record_only"

    journal.record_consumer_success(item_id, result_reference="rec_12345")
    updated = journal.get_entry(item_id)
    assert updated is not None
    assert updated["state"] == "consumer_succeeded_pending_remote_complete"
    assert updated["result_reference"] == "rec_12345"

    journal.record_remote_complete(item_id)
    completed = journal.get_entry(item_id)
    assert completed is not None
    assert completed["state"] == "remote_completed"


def test_journal_purge_expired(tmp_path: Path) -> None:
    db_path = tmp_path / "test_purge.db"
    journal = WorkerJournal(db_path=db_path)

    # Entry 1: remote_completed 10 days ago -> should be purged
    journal.record_claim("item-old", "h1", "h1", "record_only")
    journal.record_remote_complete("item-old")
    with journal._get_connection() as conn:
        old_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 10 * 86400))
        conn.execute("UPDATE worker_journal SET updated_at = ? WHERE item_id = ?", (old_iso, "item-old"))
        conn.commit()

    # Entry 2: remote_completed 1 day ago -> should NOT be purged
    journal.record_claim("item-recent", "h2", "h2", "record_only")
    journal.record_remote_complete("item-recent")

    # Entry 3: pending consumer completion 10 days ago -> should NOT be purged (non-terminal)
    journal.record_claim("item-pending", "h3", "h3", "agent_task")
    journal.record_consumer_success("item-pending", "task_99")
    with journal._get_connection() as conn:
        conn.execute("UPDATE worker_journal SET updated_at = ? WHERE item_id = ?", (old_iso, "item-pending"))
        conn.commit()

    purged = journal.purge_expired(retention_days=7)
    assert purged == 1

    assert journal.get_entry("item-old") is None
    assert journal.get_entry("item-recent") is not None
    assert journal.get_entry("item-pending") is not None
