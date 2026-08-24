import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.utils.paths import get_app_data_dir
from app.audit.audit_logger import log_audit_event
from app.destinations.outbound_lifecycle import (
    LIFECYCLE_STATES,
    TERMINAL_LIFECYCLE_STATES,
    sanitise_reason_code,
    sanitise_result_reference,
    sanitise_timestamp,
)

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
            lifecycle_columns = [
                ("lifecycle_state", "TEXT"),
                ("submitted_at", "TEXT"),
                ("claimed_at", "TEXT"),
                ("completed_at", "TEXT"),
                ("blocked_at", "TEXT"),
                ("safe_receipt", "TEXT"),
                ("blocked_reason", "TEXT"),
                ("last_status_check_at", "TEXT"),
            ]
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(outbox)").fetchall()
            }
            for column_name, column_type in lifecycle_columns:
                if column_name not in existing_columns:
                    conn.execute(
                        f"ALTER TABLE outbox ADD COLUMN {column_name} {column_type}"
                    )
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
                SET status = 'pending', attempt_count = 0, last_error = NULL,
                    next_retry_at = ?, lifecycle_state = NULL, blocked_at = NULL,
                    blocked_reason = NULL
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
        """Marks broker acceptance as the durable Submitted lifecycle state."""
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'sent', sent_at = ?, remote_msg_id = ?,
                    last_error = NULL, next_retry_at = NULL,
                    lifecycle_state = 'submitted',
                    submitted_at = COALESCE(submitted_at, ?)
                WHERE local_id = ?
                """,
                (now_str, remote_msg_id, now_str, local_id)
            )
            conn.commit()
            log_audit_event("OUTBOX_SENT_SUCCESS", "outbox", f"Task local_id={local_id} successfully marked as sent")

    def mark_failed(self, local_id: int, error_msg: str, max_attempts: int = 5) -> None:
        """Handles a failed transmission attempt, calculating the next backoff time or dead-letter status."""
        now = datetime.now(timezone.utc)
        safe_error = sanitise_reason_code(error_msg, default="LOCAL_DELIVERY_FAILED")
        
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
                f"Task {task_id} reached max retries ({attempt_count}). Moved to dead_letter."
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
                f"Task {task_id} failed (attempt {attempt_count}). Retrying in {delay_seconds}s."
            )
            
        with sqlite3.connect(self.db_path) as conn:
            if new_status == "dead_letter":
                conn.execute(
                    """
                    UPDATE outbox
                    SET status = ?, next_retry_at = ?, last_error = ?,
                        lifecycle_state = 'blocked', blocked_at = ?,
                        blocked_reason = 'LOCAL_DELIVERY_EXHAUSTED'
                    WHERE local_id = ?
                    """,
                    (new_status, next_retry, safe_error, now.isoformat(), local_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE outbox
                    SET status = ?, next_retry_at = ?, last_error = ?
                    WHERE local_id = ?
                    """,
                    (new_status, next_retry, safe_error, local_id),
                )
            conn.commit()

    def mark_duplicate(self, local_id: int, _error_type: str) -> None:
        """Handles a 409 conflict response (e.g. idempotency conflict or nonce replay).
        
        Per Step 7 rules, 409 is a submission conflict, not a successful submission.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'conflict', last_error = ?, next_retry_at = NULL,
                    lifecycle_state = 'blocked', blocked_at = ?,
                    blocked_reason = 'SUBMISSION_CONFLICT'
                WHERE local_id = ?
                """,
                ("SUBMISSION_CONFLICT", now_str, local_id)
            )
            conn.commit()
            log_audit_event(
                "OUTBOX_SUBMISSION_CONFLICT",
                "outbox",
                f"Task local_id={local_id} marked as submission conflict.",
            )

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
                SET status = 'dead_letter', last_error = 'Expired: exceeded retention period',
                    lifecycle_state = 'blocked', blocked_at = ?,
                    blocked_reason = 'LOCAL_DELIVERY_EXPIRED'
                WHERE status IN ('pending', 'sending') AND created_at <= ?
                """,
                (datetime.now(timezone.utc).isoformat(), cutoff)
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

    def get_lifecycle_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return lifecycle-only rows without payload content."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT local_id, task_id, created_at, status, attempt_count,
                       lifecycle_state,
                       submitted_at, claimed_at, completed_at, blocked_at,
                       safe_receipt, blocked_reason, last_status_check_at
                FROM outbox
                WHERE lifecycle_state IS NOT NULL OR status = 'dead_letter'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_lifecycle_stats(self) -> Dict[str, int]:
        stats = {state: 0 for state in LIFECYCLE_STATES}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT lifecycle_state, COUNT(*)
                FROM outbox
                WHERE lifecycle_state IS NOT NULL
                GROUP BY lifecycle_state
                """
            )
            for state, count in cursor.fetchall():
                if state in stats:
                    stats[state] = int(count)
        return stats

    def apply_remote_lifecycle(
        self, task_id: str, status_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Apply one authoritative status response monotonically and idempotently."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM outbox WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None

        current = dict(row)
        remote_item_id = status_data.get("item_id")
        if remote_item_id and str(remote_item_id) != task_id:
            raise ValueError("ERR_STATUS_IDENTITY_CONFLICT")

        remote_status = str(status_data.get("status") or "")
        if remote_status in {"submitted", "received", "failed_retryable", "pending"}:
            incoming_state = "submitted"
            transport_status = "sent"
        elif remote_status in {"claimed", "claiming", "processing", "running"}:
            incoming_state = "claimed"
            transport_status = "processing"
        elif remote_status == "completed":
            incoming_state = "completed"
            transport_status = "completed"
        elif remote_status in {
            "failed",
            "failed_permanent",
            "dead_letter",
            "expired",
            "cancelled",
            "manual_review",
        }:
            incoming_state = "blocked"
            transport_status = "failed"
        else:
            return current

        current_state = current.get("lifecycle_state")
        if current_state in TERMINAL_LIFECYCLE_STATES and incoming_state != current_state:
            return current
        rank = {"submitted": 1, "claimed": 2, "completed": 3, "blocked": 3}
        if current_state in rank and rank[incoming_state] < rank[current_state]:
            incoming_state = str(current_state)
            transport_status = str(current.get("status") or transport_status)

        submitted_at = sanitise_timestamp(status_data.get("created_at"))
        claimed_at = sanitise_timestamp(status_data.get("claimed_at"))
        completed_at = sanitise_timestamp(status_data.get("completed_at"))
        blocked_at = sanitise_timestamp(status_data.get("failed_at"))
        receipt = sanitise_result_reference(status_data.get("result_reference"))
        blocked_reason = None
        if incoming_state == "blocked":
            blocked_reason = sanitise_reason_code(
                status_data.get("blocked_reason")
                or status_data.get("last_error_code")
                or status_data.get("failure_reason")
                or remote_status.upper()
            )

        now_str = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = ?, lifecycle_state = ?,
                    submitted_at = COALESCE(?, submitted_at, sent_at, created_at),
                    claimed_at = COALESCE(?, claimed_at),
                    completed_at = COALESCE(?, completed_at),
                    blocked_at = COALESCE(?, blocked_at),
                    safe_receipt = COALESCE(?, safe_receipt),
                    blocked_reason = COALESCE(?, blocked_reason),
                    last_status_check_at = ?
                WHERE task_id = ?
                """,
                (
                    transport_status,
                    incoming_state,
                    submitted_at,
                    claimed_at,
                    completed_at,
                    blocked_at,
                    receipt,
                    blocked_reason,
                    now_str,
                    task_id,
                ),
            )
            conn.commit()

        log_audit_event(
            "OUTBOUND_LIFECYCLE_RECONCILED",
            "outbox",
            f"Task {task_id} reconciled to {incoming_state}.",
        )
        return self.get_by_task_id(task_id)

    def update_task_status(
        self, 
        local_id: int, 
        status: str, 
        last_error: Optional[str] = None, 
        remote_msg_id: Optional[str] = None
    ) -> None:
        """Explicitly updates the status, last_error, and remote_msg_id of a task."""
        safe_error = (
            sanitise_reason_code(last_error, default="REMOTE_STATUS_FAILED")
            if last_error
            else None
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = ?, last_error = ?, remote_msg_id = ?, next_retry_at = NULL
                WHERE local_id = ?
                """,
                (status, safe_error, remote_msg_id, local_id)
            )
            conn.commit()
            log_audit_event("OUTBOX_STATUS_UPDATED", "outbox", f"Task local_id={local_id} updated to status={status}")

    def get_stats(self) -> Dict[str, int]:
        """Returns the counts of messages in each status."""
        stats = {
            "pending": 0, "sending": 0, "sent": 0, "failed": 0, 
            "dead_letter": 0, "archived": 0, "completed": 0, "processing": 0, "conflict": 0
        }
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT status, COUNT(*) FROM outbox GROUP BY status")
            for row in cursor.fetchall():
                status, count = row
                stats[status] = count
        return stats
