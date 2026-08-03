"""Worker Journal — Local SQLite persistent store for tracking worker processing states and preventing duplicate side-effects."""

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.paths import get_app_data_dir

logger = logging.getLogger(__name__)


def get_journal_db_path() -> Path:
    """Returns the configured or default path to the SQLite worker journal database."""
    env_path = os.environ.get("CVN_WORKER_JOURNAL_PATH")
    if env_path:
        path = Path(env_path)
    else:
        path = get_app_data_dir() / "worker_journal.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class JournalIdentityConflictError(Exception):
    """Raised when re-claiming an existing item_id with a conflicting payload_hash, content_hash, or consumer_kind."""

    pass


class WorkerJournal:
    """Local SQLite journal tracking item states: claimed -> consumer_succeeded_pending_remote_complete -> remote_completed (or failed)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or get_journal_db_path()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_file_permissions(self) -> None:
        if os.name != "nt" and self.db_path.exists():
            try:
                os.chmod(self.db_path, 0o600)
            except Exception as exc:
                logger.warning(f"Failed setting 0600 permissions on worker journal: {exc}")

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_journal (
                    item_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    consumer_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_reference TEXT,
                    error_code TEXT
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wj_state_updated ON worker_journal(state, updated_at);"
            )
            conn.commit()
        self._apply_file_permissions()

    def record_claim(
        self,
        item_id: str,
        payload_hash: str,
        content_hash: str,
        consumer_kind: str,
    ) -> Dict[str, Any]:
        """Records or verifies a claimed item state with immutable identity checking."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        p_hash = payload_hash or ""
        c_hash = content_hash or ""
        c_kind = consumer_kind or ""

        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT payload_hash, content_hash, consumer_kind, state FROM worker_journal WHERE item_id = ?",
                (item_id,),
            )
            existing = cur.fetchone()
            if existing:
                ex_dict = dict(existing)
                # Verify immutable identity fields match
                if (
                    ex_dict["payload_hash"] != p_hash
                    or ex_dict["content_hash"] != c_hash
                    or ex_dict["consumer_kind"] != c_kind
                ):
                    logger.error(
                        f"JOURNAL_IDENTITY_CONFLICT: Item {item_id} re-claimed with mismatching hashes or consumer kind."
                    )
                    raise JournalIdentityConflictError(
                        f"Item {item_id} journal conflict: existing identity ({ex_dict['payload_hash']}, {ex_dict['content_hash']}, {ex_dict['consumer_kind']}) "
                        f"does not match new claim ({p_hash}, {c_hash}, {c_kind})."
                    )
                # Touch updated_at timestamp without modifying state or identity
                conn.execute(
                    "UPDATE worker_journal SET updated_at = ? WHERE item_id = ?",
                    (now, item_id),
                )
                conn.commit()
            else:
                conn.execute(
                    """
                    INSERT INTO worker_journal (
                        item_id, payload_hash, content_hash, consumer_kind, state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'claimed', ?, ?);
                    """,
                    (item_id, p_hash, c_hash, c_kind, now, now),
                )
                conn.commit()
        self._apply_file_permissions()
        return self.get_entry(item_id) or {}

    def record_consumer_success(self, item_id: str, result_reference: str) -> None:
        """Transitions state to consumer_succeeded_pending_remote_complete with safe result reference."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE worker_journal
                SET state = 'consumer_succeeded_pending_remote_complete',
                    result_reference = ?,
                    updated_at = ?
                WHERE item_id = ?;
                """,
                (result_reference or "", now, item_id),
            )
            conn.commit()

    def record_remote_complete(self, item_id: str) -> None:
        """Transitions state to remote_completed."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE worker_journal
                SET state = 'remote_completed',
                    updated_at = ?
                WHERE item_id = ?;
                """,
                (now, item_id),
            )
            conn.commit()

    def record_failure(self, item_id: str, error_code: str) -> None:
        """Transitions state to failed with safe error code."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE worker_journal
                SET state = 'failed',
                    error_code = ?,
                    updated_at = ?
                WHERE item_id = ?;
                """,
                (error_code or "UNSPECIFIED_ERROR", now, item_id),
            )
            conn.commit()

    def get_entry(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves entry by item_id if present."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT item_id, payload_hash, content_hash, consumer_kind, state,
                       created_at, updated_at, result_reference, error_code
                FROM worker_journal
                WHERE item_id = ?;
                """,
                (item_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

    def purge_expired(self, retention_days: Optional[int] = None) -> int:
        """Purges remote_completed records older than retention_days.

        Never purges non-terminal entries ('claimed', 'consumer_succeeded_pending_remote_complete').
        """
        if retention_days is None:
            try:
                retention_days = int(os.environ.get("CVN_WORKER_JOURNAL_RETENTION_DAYS", "7"))
            except ValueError:
                retention_days = 7

        if retention_days < 1 or retention_days > 365:
            logger.warning(f"Invalid retention days {retention_days}; clamping to 7 days.")
            retention_days = 7

        cutoff_seconds = time.time() - (retention_days * 86400)
        cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff_seconds))

        with self._get_connection() as conn:
            cur = conn.execute(
                """
                DELETE FROM worker_journal
                WHERE state = 'remote_completed' AND updated_at < ?;
                """,
                (cutoff_iso,),
            )
            purged_count = cur.rowcount
            conn.commit()

        if purged_count > 0:
            logger.info(f"Purged {purged_count} expired remote_completed journal entries older than {retention_days} days.")
        return purged_count
