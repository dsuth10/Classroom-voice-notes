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
