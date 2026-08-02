import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.utils.paths import get_app_data_dir
from app.audit.audit_logger import log_audit_event

class ExternalOutbox:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = get_app_data_dir() / "external_outbox.db"
        else:
            self.db_path = db_path
            
        self._init_db()

    def _init_db(self) -> None:
        """Initialise database schema if it does not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    local_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id         TEXT NOT NULL UNIQUE,
                    created_at      TEXT NOT NULL,
                    endpoint_url    TEXT NOT NULL,
                    payload_json    TEXT NOT NULL,
                    payload_hash    TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    attempt_count   INTEGER NOT NULL DEFAULT 0,
                    next_retry_at   TEXT,
                    last_error      TEXT,
                    sent_at         TEXT,
                    remote_msg_id   TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    nonce           TEXT NOT NULL,
                    archived_at     TEXT,
                    note_path       TEXT,
                    target_agent    TEXT
                );
            """)
            # Migration: add archived_at if it is missing
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN archived_at TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration: add note_path if it is missing
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN note_path TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration: add target_agent if it is missing
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN target_agent TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration PR3: add schema_version column
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN schema_version TEXT NOT NULL DEFAULT 'cvn.agent_task.v1'")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration PR3: add item_kind column
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN item_kind TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration PR3: add content_hash column
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN content_hash TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration PR3: add release_basis column
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN release_basis TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migration PR3: add review_id column
            try:
                conn.execute("ALTER TABLE outbox ADD COLUMN review_id TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def enqueue(
        self,
        task_id: str,
        endpoint_url: str,
        payload_json: str,
        payload_hash: str,
        idempotency_key: str,
        nonce: str,
        *,
        schema_version: str,
        note_path: Optional[str] = None,
        target_agent: Optional[str] = None,
        item_kind: Optional[str] = None,
        content_hash: Optional[str] = None,
        release_basis: Optional[str] = None,
        review_id: Optional[str] = None,
    ) -> int:
        """Enqueues a new pending task in the local outbox."""
        valid_schemas = {"cvn.agent_task.v1", "cvn.outbound_item.v2"}
        if schema_version not in valid_schemas:
            raise ValueError(f"Unsupported schema_version: '{schema_version}'. Must be one of {valid_schemas}")

        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO outbox (
                    task_id, created_at, endpoint_url, payload_json, payload_hash,
                    status, attempt_count, next_retry_at, idempotency_key, nonce,
                    note_path, target_agent, schema_version, item_kind,
                    content_hash, release_basis, review_id
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    now_str,
                    endpoint_url,
                    payload_json,
                    payload_hash,
                    now_str,
                    idempotency_key,
                    nonce,
                    note_path,
                    target_agent,
                    schema_version,
                    item_kind,
                    content_hash,
                    release_basis,
                    review_id,
                )
            )
            conn.commit()
            local_id = cursor.lastrowid
            assert local_id is not None
            log_audit_event("OUTBOX_ENQUEUED", "outbox", f"Task {task_id} enqueued locally (local_id: {local_id})")
            return local_id


    def get_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Returns outbox row by task_id if exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM outbox WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def get_dead_letter_tasks(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Returns tasks in dead_letter status (ordered by local_id desc)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM outbox
                WHERE status = 'dead_letter'
                ORDER BY local_id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            return [dict(row) for row in cursor.fetchall()]

    def retry_dead_letter_task(self, local_id: int) -> bool:
        """Atomically retries a single dead_letter task, resetting attempts and verifying environment."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT endpoint_url, status FROM outbox WHERE local_id = ?", (local_id,))
            row = cursor.fetchone()
            if not row:
                return False
            endpoint_url = row["endpoint_url"]
            status = row["status"]

        if status != "dead_letter":
            return False

        # Validate environment match for endpoint_url (CVN-BL-014)
        from app.config.environment import validate_broker_endpoint
        try:
            validate_broker_endpoint(endpoint_url)
        except RuntimeError as exc:
            log_audit_event(
                "OUTBOX_RETRY_REFUSED",
                "outbox",
                f"Refused to retry task {local_id}: {exc}",
            )
            return False

        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE outbox
                SET status = 'pending', attempt_count = 0, last_error = NULL, next_retry_at = ?
                WHERE local_id = ? AND status = 'dead_letter'
                """,
                (now_str, local_id)
            )
            conn.commit()
            updated = cursor.rowcount == 1
            if updated:
                log_audit_event("OUTBOX_DEAD_LETTER_RETRY", "outbox", f"Reset dead_letter task local_id={local_id} to pending")
            return updated

    def archive_dead_letter_task(self, local_id: int) -> bool:
        """Moves a dead_letter task to archived status, setting archived_at."""
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE outbox
                SET status = 'archived', archived_at = ?
                WHERE local_id = ? AND status = 'dead_letter'
                """,
                (now_str, local_id)
            )
            conn.commit()
            updated = cursor.rowcount == 1
            if updated:
                log_audit_event("OUTBOX_DEAD_LETTER_ARCHIVED", "outbox", f"Archived dead_letter task local_id={local_id}")
            return updated

    def mark_sending(self, local_id: int) -> None:
        """Marks a task as sending and increments the attempt count."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'sending', attempt_count = attempt_count + 1
                WHERE local_id = ?
                """,
                (local_id,)
            )
            conn.commit()

    def mark_sent(self, local_id: int, remote_msg_id: Optional[str] = None) -> None:
        """Marks a task as successfully sent to the remote broker."""
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'sent', sent_at = ?, remote_msg_id = ?,
                    last_error = NULL, next_retry_at = NULL
                WHERE local_id = ?
                """,
                (now_str, remote_msg_id, local_id)
            )
            conn.commit()
            log_audit_event("OUTBOX_SENT_SUCCESS", "outbox", f"Task local_id={local_id} successfully marked as sent")

    def mark_failed(self, local_id: int, error_msg: str, max_attempts: int = 5) -> None:
        """Handles a failed transmission attempt, calculating the next backoff time or dead-letter status."""
        now = datetime.now(timezone.utc)
        
        # Read the current attempt count
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT attempt_count, task_id FROM outbox WHERE local_id = ?", (local_id,))
            row = cursor.fetchone()
            if not row:
                return
            
            attempt_count = row["attempt_count"]
            task_id = row["task_id"]
            
        if attempt_count >= max_attempts:
            new_status = "dead_letter"
            next_retry = None
            log_audit_event(
                "OUTBOX_DEAD_LETTER", 
                "outbox", 
                f"Task {task_id} reached max retries ({attempt_count}). Moved to dead_letter. Error: {error_msg}"
            )
        else:
            new_status = "pending"
            # Backoff: 3s -> 9s -> 27s -> 81s -> 243s -> then hourly (3600s)
            backoff_delays = [3, 9, 27, 81, 243]
            idx = attempt_count - 1
            delay_seconds = backoff_delays[idx] if idx < len(backoff_delays) else 3600
            next_retry = (now + timedelta(seconds=delay_seconds)).isoformat()
            log_audit_event(
                "OUTBOX_RETRY_SCHEDULED", 
                "outbox", 
                f"Task {task_id} failed (attempt {attempt_count}). Retrying in {delay_seconds}s. Error: {error_msg}"
            )
            
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = ?, next_retry_at = ?, last_error = ?
                WHERE local_id = ?
                """,
                (new_status, next_retry, error_msg, local_id)
            )
            conn.commit()

    def mark_duplicate(self, local_id: int, error_type: str) -> None:
        """Handles a 409 conflict response (e.g. duplicate idempotency or nonce).
        
        Since the server already has the record, we treat this as a successful sent.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'sent', sent_at = ?, last_error = ?, next_retry_at = NULL
                WHERE local_id = ?
                """,
                (now_str, f"Duplicate conflict (409): {error_type}", local_id)
            )
            conn.commit()
            log_audit_event("OUTBOX_DUPLICATE_RESOLVED", "outbox", f"Task local_id={local_id} marked as sent due to 409 collision ({error_type})")

    def get_pending(self) -> List[Dict[str, Any]]:
        """Returns all outbox records that are currently 'pending' and due for retry."""
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM outbox
                WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY local_id ASC
                """,
                (now_str,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def expire_old(self, days: int = 7) -> int:
        """Moves pending/sending tasks older than specified days to dead_letter."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE outbox
                SET status = 'dead_letter', last_error = 'Expired: exceeded retention period'
                WHERE status IN ('pending', 'sending') AND created_at <= ?
                """,
                (cutoff,)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                log_audit_event("OUTBOX_EXPIRY", "outbox", f"Expired {count} pending tasks older than {days} days to dead_letter")
            return count

    def get_unfinished_tasks(self) -> List[Dict[str, Any]]:
        """Returns all outbox records that are in 'sent' or 'processing' status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM outbox
                WHERE status IN ('sent', 'processing')
                ORDER BY local_id ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_task_status(
        self, 
        local_id: int, 
        status: str, 
        last_error: Optional[str] = None, 
        remote_msg_id: Optional[str] = None
    ) -> None:
        """Explicitly updates the status, last_error, and remote_msg_id of a task."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = ?, last_error = ?, remote_msg_id = ?, next_retry_at = NULL
                WHERE local_id = ?
                """,
                (status, last_error, remote_msg_id, local_id)
            )
            conn.commit()
            log_audit_event("OUTBOX_STATUS_UPDATED", "outbox", f"Task local_id={local_id} updated to status={status}")

    def get_stats(self) -> Dict[str, int]:
        """Returns the counts of messages in each status."""
        stats = {
            "pending": 0, "sending": 0, "sent": 0, "failed": 0, 
            "dead_letter": 0, "archived": 0, "completed": 0, "processing": 0
        }
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT status, COUNT(*) FROM outbox GROUP BY status")
            for row in cursor.fetchall():
                status, count = row
                stats[status] = count
        return stats
