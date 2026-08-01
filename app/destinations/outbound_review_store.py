"""Outbound Review Store - SQLite persistence for outbound review items."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from app.audit.audit_logger import log_audit_event
from app.utils.paths import get_app_data_dir


def compute_content_hash(
    item_kind: str,
    target_agent: Optional[str],
    content: Dict[str, Any],
    task: Optional[Dict[str, Any]] = None,
) -> str:
    """Computes a deterministic SHA-256 hash of the outbound content fields."""
    canonical_obj = {
        "item_kind": item_kind,
        "target_agent": target_agent or "",
        "content": content,
        "task": task or {},
    }
    canonical_bytes = json.dumps(
        canonical_obj, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


class OutboundReviewStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = get_app_data_dir() / "outbound_review.db"
        else:
            self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_items (
                    review_id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id             TEXT UNIQUE NOT NULL,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL,
                    note_path           TEXT NOT NULL,
                    item_kind           TEXT NOT NULL,
                    target_agent        TEXT,
                    draft_json          TEXT NOT NULL,
                    content_hash        TEXT NOT NULL,
                    assessment_json     TEXT NOT NULL,
                    status              TEXT NOT NULL,
                    approved_at         TEXT,
                    approval_method     TEXT,
                    rejected_at         TEXT,
                    rejection_reason    TEXT,
                    outbox_local_id     INTEGER
                );
            """)
            conn.commit()

    def create_review_item(
        self,
        item_id: str,
        note_path: str,
        item_kind: str,
        target_agent: Optional[str],
        draft_json: str,
        assessment_json: str,
        status: str = "awaiting_review",
    ) -> Optional[Dict[str, Any]]:
        """Creates a new outbound review record with a computed content hash."""
        now = datetime.now(timezone.utc).isoformat()
        draft_dict = (
            json.loads(draft_json) if isinstance(draft_json, str) else draft_json
        )
        content = draft_dict.get("content", {})
        task = draft_dict.get("task")
        content_hash = compute_content_hash(
            item_kind, target_agent, content, task
        )
        draft_str = (
            json.dumps(draft_dict)
            if not isinstance(draft_json, str)
            else draft_json
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_items (
                    item_id, created_at, updated_at, note_path, item_kind,
                    target_agent, draft_json, content_hash, assessment_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    now,
                    now,
                    note_path,
                    item_kind,
                    target_agent,
                    draft_str,
                    content_hash,
                    assessment_json,
                    status,
                ),
            )
            conn.commit()

        log_audit_event(
            "OUTBOUND_REVIEW_CREATED",
            "review_store",
            f"Item {item_id} created with status '{status}'.",
        )
        return self.get_by_id(item_id)

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def get_awaiting_review(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM review_items WHERE status = 'awaiting_review'"
                " ORDER BY created_at DESC"
            )
            return [dict(r) for r in cursor.fetchall()]

    def update_draft(
        self,
        item_id: str,
        draft_dict: Dict[str, Any],
        assessment_json: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Updates draft content, recalculates content_hash, and resets any approval."""
        existing = self.get_by_id(item_id)
        if not existing:
            return None

        item_kind = draft_dict.get("item_kind", existing["item_kind"])
        target_agent = draft_dict.get("target_agent", existing["target_agent"])
        content = draft_dict.get("content", {})
        task = draft_dict.get("task")
        new_hash = compute_content_hash(item_kind, target_agent, content, task)
        now = datetime.now(timezone.utc).isoformat()
        draft_str = json.dumps(draft_dict)

        with sqlite3.connect(self.db_path) as conn:
            if assessment_json:
                conn.execute(
                    """
                    UPDATE review_items
                    SET draft_json = ?, content_hash = ?, assessment_json = ?,
                        updated_at = ?, status = 'awaiting_review', approved_at = NULL, approval_method = NULL
                    WHERE item_id = ?
                    """,
                    (draft_str, new_hash, assessment_json, now, item_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE review_items
                    SET draft_json = ?, content_hash = ?, updated_at = ?,
                        status = 'awaiting_review', approved_at = NULL, approval_method = NULL
                    WHERE item_id = ?
                    """,
                    (draft_str, new_hash, now, item_id),
                )
            conn.commit()

        log_audit_event(
            "OUTBOUND_REVIEW_EDITED",
            "review_store",
            f"Item {item_id} draft updated; approval reset.",
        )
        return self.get_by_id(item_id)

    def approve(
        self, item_id: str, approval_method: str = "manual_ui"
    ) -> Optional[Dict[str, Any]]:
        """Marks item approved, recording approved_at and approval_method."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE review_items
                SET status = 'approved', approved_at = ?, approval_method = ?, updated_at = ?
                WHERE item_id = ?
                """,
                (now, approval_method, now, item_id),
            )
            conn.commit()
        log_audit_event(
            "OUTBOUND_REVIEW_APPROVED",
            "review_store",
            f"Item {item_id} approved via {approval_method}.",
        )
        return self.get_by_id(item_id)

    def reject(
        self, item_id: str, reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE review_items
                SET status = 'rejected', rejected_at = ?, rejection_reason = ?, updated_at = ?
                WHERE item_id = ?
                """,
                (now, reason, now, item_id),
            )
            conn.commit()
        log_audit_event(
            "OUTBOUND_REVIEW_REJECTED",
            "review_store",
            f"Item {item_id} rejected.",
        )
        return self.get_by_id(item_id)

    def mark_queued(
        self, item_id: str, outbox_local_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE review_items
                SET status = 'queued', outbox_local_id = ?, updated_at = ?
                WHERE item_id = ?
                """,
                (outbox_local_id, now, item_id),
            )
            conn.commit()
        log_audit_event(
            "OUTBOUND_QUEUED", "review_store", f"Item {item_id} queued."
        )
        return self.get_by_id(item_id)

    def mark_sent(self, item_id: str) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE review_items SET status = 'sent', updated_at = ? WHERE"
                " item_id = ?",
                (now, item_id),
            )
            conn.commit()
        log_audit_event(
            "OUTBOUND_SENT", "review_store", f"Item {item_id} sent."
        )
        return self.get_by_id(item_id)

    def expire_old(self, days: int = 30) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE review_items SET status = 'expired', updated_at = ?"
                " WHERE created_at < ? AND status = 'awaiting_review'",
                (datetime.now(timezone.utc).isoformat(), cutoff),
            )
            count = cursor.rowcount
            conn.commit()
        return count

    def get_stats(self) -> Dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) FROM review_items GROUP BY status"
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def purge_expired_reviews(self, retention_days: int = 30) -> int:
        """Purges old terminal review records older than retention_days."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM review_items
                WHERE updated_at < ?
                  AND status IN ('sent', 'rejected', 'expired', 'auto_approved')
                """,
                (cutoff,),
            )
            count = cursor.rowcount
            conn.commit()
        log_audit_event(
            "OUTBOUND_REVIEW_RETENTION_PURGE",
            "review_store",
            f"Purged {count} expired review items older than {retention_days} days.",
        )
        return count
