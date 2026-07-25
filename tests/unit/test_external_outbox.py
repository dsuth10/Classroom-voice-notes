import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from app.destinations.external_outbox import ExternalOutbox

@pytest.fixture
def outbox(tmp_path: Path) -> ExternalOutbox:
    db_file = tmp_path / "test_outbox.db"
    return ExternalOutbox(db_file)

def test_enqueue_and_get_pending(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue(
        task_id="CVN-1",
        endpoint_url="http://test.url",
        payload_json='{"test":true}',
        payload_hash="hash123",
        idempotency_key="idem1",
        nonce="nonce1"
    )
    assert local_id == 1
    
    pending = outbox.get_pending()
    assert len(pending) == 1
    assert pending[0]["task_id"] == "CVN-1"
    assert pending[0]["status"] == "pending"
    assert pending[0]["attempt_count"] == 0

def test_mark_sending_and_sent(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue("CVN-2", "http://test.url", "{}", "hash", "idem2", "nonce2")
    
    outbox.mark_sending(local_id)
    pending = outbox.get_pending()
    # Should not return tasks currently sending (status = 'sending')
    assert len(pending) == 0
    
    outbox.mark_sent(local_id, "msg_999")
    stats = outbox.get_stats()
    assert stats["sent"] == 1
    assert stats["pending"] == 0
    with sqlite3.connect(outbox.db_path) as conn:
        next_retry_at = conn.execute(
            "SELECT next_retry_at FROM outbox WHERE local_id = ?",
            (local_id,),
        ).fetchone()[0]
    assert next_retry_at is None

def test_mark_failed_exponential_backoff(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue("CVN-3", "http://test.url", "{}", "hash", "idem3", "nonce3")
    
    # 1st failure (attempt increments to 1 when sending, then we fail it)
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Timeout error", max_attempts=3)
    
    pending = outbox.get_pending()
    # It has a future next_retry_at, so it shouldn't be pending immediately
    assert len(pending) == 0
    
    # Check stats shows pending
    stats = outbox.get_stats()
    assert stats["pending"] == 1
    
    # 2nd failure
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Internal Server Error", max_attempts=3)
    
    # 3rd failure -> should move to dead_letter
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Bad Gateway", max_attempts=3)
    
    stats = outbox.get_stats()
    assert stats["dead_letter"] == 1
    assert stats["pending"] == 0

def test_mark_duplicate_409(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue("CVN-4", "http://test.url", "{}", "hash", "idem4", "nonce4")
    outbox.mark_duplicate(local_id, "duplicate_idempotency_key")
    
    stats = outbox.get_stats()
    assert stats["sent"] == 1
    
    # Check database content directly
    with sqlite3.connect(outbox.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM outbox WHERE local_id = ?", (local_id,)).fetchone()
        assert row["status"] == "sent"
        assert "Duplicate conflict" in row["last_error"]
        assert row["next_retry_at"] is None


def test_enqueue_persists_target_agent(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue(
        "CVN-TARGET",
        "http://test.url",
        "{}",
        "hash",
        "idem-target",
        "nonce-target",
        target_agent="hermes",
    )

    with sqlite3.connect(outbox.db_path) as conn:
        target_agent = conn.execute(
            "SELECT target_agent FROM outbox WHERE local_id = ?",
            (local_id,),
        ).fetchone()[0]

    assert target_agent == "hermes"

def test_expire_old(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue("CVN-5", "http://test.url", "{}", "hash", "idem5", "nonce5")
    
    # Manipulate created_at to be 8 days ago
    eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with sqlite3.connect(outbox.db_path) as conn:
        conn.execute("UPDATE outbox SET created_at = ? WHERE local_id = ?", (eight_days_ago, local_id))
        conn.commit()
        
    expired_count = outbox.expire_old(days=7)
    assert expired_count == 1
    
    stats = outbox.get_stats()
    assert stats["dead_letter"] == 1
    assert stats["pending"] == 0

def test_selective_dead_letter_retry(outbox: ExternalOutbox, monkeypatch) -> None:
    # 1. Enqueue task and mark it dead_letter
    local_id = outbox.enqueue("CVN-10", "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-complete-task", "{}", "hash", "idem10", "nonce10")
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Max attempts reached", max_attempts=1)
    
    assert outbox.get_stats()["dead_letter"] == 1

    # Mock environment to staging
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")

    # 2. Selective retry dead_letter task
    res = outbox.retry_dead_letter_task(local_id)
    assert res is True
    
    # Verify stats
    stats = outbox.get_stats()
    assert stats["pending"] == 1
    assert stats["dead_letter"] == 0

def test_selective_dead_letter_retry_wrong_env(outbox: ExternalOutbox, monkeypatch) -> None:
    # Task has staging URL
    local_id = outbox.enqueue("CVN-11", "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-complete-task", "{}", "hash", "idem11", "nonce11")
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Max attempts reached", max_attempts=1)

    # Set env to production
    monkeypatch.setenv("CVN_BROKER_ENV", "production")

    # Retry should fail because URL doesn't match production
    res = outbox.retry_dead_letter_task(local_id)
    assert res is False
    assert outbox.get_stats()["dead_letter"] == 1


def test_selective_dead_letter_retry_rejects_lookalike_host(
    outbox: ExternalOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_id = outbox.enqueue(
        "CVN-LOOKALIKE",
        "https://ukqkkgzimhtjhlnmlyao.supabase.co.evil.example/functions/v1/cvn-submit-task",
        "{}",
        "hash",
        "idem-lookalike",
        "nonce-lookalike",
    )
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Max attempts reached", max_attempts=1)
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")

    assert outbox.retry_dead_letter_task(local_id) is False
    assert outbox.get_stats()["dead_letter"] == 1

def test_selective_dead_letter_retry_non_dead_letter(outbox: ExternalOutbox, monkeypatch) -> None:
    local_id = outbox.enqueue("CVN-12", "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-complete-task", "{}", "hash", "idem12", "nonce12")
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")
    
    # Try to retry a task that is still 'pending'
    res = outbox.retry_dead_letter_task(local_id)
    assert res is False

def test_archive_dead_letter_task(outbox: ExternalOutbox) -> None:
    local_id = outbox.enqueue("CVN-13", "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-complete-task", "{}", "hash", "idem13", "nonce13")
    outbox.mark_sending(local_id)
    outbox.mark_failed(local_id, "Max attempts reached", max_attempts=1)

    # Archive it
    res = outbox.archive_dead_letter_task(local_id)
    assert res is True

    stats = outbox.get_stats()
    assert stats["archived"] == 1
    assert stats["dead_letter"] == 0

    # Ensure archived task cannot be retried
    res_retry = outbox.retry_dead_letter_task(local_id)
    assert res_retry is False
