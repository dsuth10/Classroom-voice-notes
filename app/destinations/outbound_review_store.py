"""Outbound Review Store - SQLite persistence for outbound review items."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import sqlite3
from typing import Any, Dict, List, Optional

from app.audit.audit_logger import log_audit_event
from app.destinations.canonical_json import compute_canonical_content_hash
from app.utils.paths import get_app_data_dir


ALLOWED_TRANSITIONS: Dict[str, set[str]] = {
    "awaiting_review": {"awaiting_review", "approved_pending_enqueue", "rejected", "expired"},
    "approved_pending_enqueue": {"queued", "enqueue_failed"},
    "enqueue_failed": {"approved_pending_enqueue", "rejected"},
    "queued": {"sent", "delivery_failed"},
    "delivery_failed": {"queued", "rejected"},
    "sent": set(),
    "rejected": set(),
    "expired": set(),
}


def compute_content_hash(
    item_kind: str,
    target_agent: Optional[str],
    content: Dict[str, Any],
    task: Optional[Dict[str, Any]] = None,
) -> str:
    """Computes a deterministic SHA-256 hash of the outbound content fields."""
    _, digest = compute_canonical_content_hash(
        item_kind=item_kind,
        target_agent=target_agent,
        content=content,
        task=task,
    )
    return digest



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
                    review_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id               TEXT UNIQUE NOT NULL,
                    created_at            TEXT NOT NULL,
                    updated_at            TEXT NOT NULL,
                    note_path             TEXT NOT NULL,
                    item_kind             TEXT NOT NULL,
                    target_agent          TEXT,
                    draft_json            TEXT NOT NULL,
                    content_hash          TEXT NOT NULL,
                    approved_content_hash TEXT,
                    assessment_json       TEXT NOT NULL,
                    status                TEXT NOT NULL,
                    approved_at           TEXT,
                    approval_method       TEXT,
                    rejected_at           TEXT,
                    rejection_reason      TEXT,
                    queued_at             TEXT,
                    sent_at               TEXT,
                    last_error            TEXT,
                    retry_count           INTEGER DEFAULT 0,
                    outbox_local_id       INTEGER
                );
            """)
            
            # Migration helpers for existing databases
            existing_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(review_items)").fetchall()
            }
            new_columns = [
                ("approved_content_hash", "TEXT"),
                ("queued_at", "TEXT"),
                ("sent_at", "TEXT"),
                ("last_error", "TEXT"),
                ("retry_count", "INTEGER DEFAULT 0"),
                ("release_basis", "TEXT"),
            ]
            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE review_items ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError:
                        pass
            conn.commit()

    def _execute_checked_transition(
        self,
        item_id: str,
        expected_statuses: set[str],
        target_status: str,
        update_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_by_id(item_id)
        if not existing:
            raise ValueError(f"Item not found: {item_id}")

        current_status = existing["status"]
        if current_status not in expected_statuses:
            raise ValueError(
                f"Illegal transition for item '{item_id}': current state '{current_status}' "
                f"is not in allowed source states {sorted(list(expected_statuses))} for transition to '{target_status}'."
            )

        now = datetime.now(timezone.utc).isoformat()
        update_params["updated_at"] = now
        update_params["status"] = target_status

        set_clauses = [f"{col} = ?" for col in update_params.keys()]
        values = list(update_params.values())

        placeholders = ",".join(["?"] * len(expected_statuses))
        where_clause = f"WHERE item_id = ? AND status IN ({placeholders})"
        values.append(item_id)
        values.extend(list(expected_statuses))

        sql = f"UPDATE review_items SET {', '.join(set_clauses)} {where_clause}"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Transition failed for item '{item_id}': state changed concurrently from '{current_status}'."
                )

        log_audit_event(
            "OUTBOUND_REVIEW_TRANSITION",
            "review_store",
            f"Item {item_id} transitioned from '{current_status}' to '{target_status}'.",
        )
        return self.get_by_id(item_id)

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
        """Updates draft content and columns, recalculates content_hash, and resets any approval."""
        existing = self.get_by_id(item_id)
        if not existing:
            return None

        item_kind = str(
            draft_dict.get("item_kind") or existing.get("item_kind") or "record_only"
        )
        target_agent = str(
            draft_dict.get("target_agent")
            or existing.get("target_agent")
            or "openclaw"
        )
        content = draft_dict.get("content", {})
        task = draft_dict.get("task")
        new_hash = compute_content_hash(item_kind, target_agent, content, task)

        draft_str = json.dumps(draft_dict)

        update_params = {
            "item_kind": item_kind,
            "target_agent": target_agent,
            "draft_json": draft_str,
            "content_hash": new_hash,
            "approved_content_hash": None,
            "approved_at": None,
            "approval_method": None,
        }
        if assessment_json is not None:
            update_params["assessment_json"] = assessment_json

        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"awaiting_review"},
            target_status="awaiting_review",
            update_params=update_params,
        )

    def approve(
        self,
        item_id: str,
        approval_method: str = "manual_ui",
        approved_content_hash: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Marks item approved_pending_enqueue, storing approved_content_hash and approved_at."""
        existing = self.get_by_id(item_id)
        if not existing:
            return None

        approved_hash = approved_content_hash or existing.get("content_hash")
        now = datetime.now(timezone.utc).isoformat()

        release_basis = "trusted_mode" if approval_method == "trusted_mode" else "human_approval"
        update_params = {
            "approved_content_hash": approved_hash,
            "approved_at": now,
            "approval_method": approval_method,
            "release_basis": release_basis,
        }


        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"awaiting_review"},
            target_status="approved_pending_enqueue",
            update_params=update_params,
        )


    def mark_enqueue_failed(self, item_id: str, last_error: str) -> Optional[Dict[str, Any]]:
        """Moves item to enqueue_failed with error details.

        Allowed from both 'approved_pending_enqueue' and 'enqueue_failed' (re-attempt failure)
        to prevent an illegal self-transition error masking the original error.
        """
        update_params = {"last_error": last_error}
        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"approved_pending_enqueue", "enqueue_failed"},
            target_status="enqueue_failed",
            update_params=update_params,
        )

    def reject(
        self, item_id: str, reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Rejects item from awaiting_review, enqueue_failed, or delivery_failed."""
        now = datetime.now(timezone.utc).isoformat()
        update_params = {
            "rejected_at": now,
            "rejection_reason": reason,
        }
        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"awaiting_review", "enqueue_failed", "delivery_failed"},
            target_status="rejected",
            update_params=update_params,
        )

    def mark_queued(
        self, item_id: str, outbox_local_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Marks item queued after durable outbox insertion."""
        now = datetime.now(timezone.utc).isoformat()
        update_params = {
            "queued_at": now,
            "outbox_local_id": outbox_local_id,
        }
        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"approved_pending_enqueue", "enqueue_failed"},
            target_status="queued",
            update_params=update_params,
        )

    def mark_delivery_failed(self, item_id: str, last_error: str) -> Optional[Dict[str, Any]]:
        """Marks queued item as delivery_failed with error details and incremented retry count."""
        existing = self.get_by_id(item_id)
        current_retries = existing.get("retry_count", 0) if existing else 0
        update_params = {
            "last_error": last_error,
            "retry_count": current_retries + 1,
        }
        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"queued"},
            target_status="delivery_failed",
            update_params=update_params,
        )

    def mark_sent(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Marks item as sent once dispatch is completed. Idempotent if already sent."""
        existing = self.get_by_id(item_id)
        if existing and existing.get("status") == "sent":
            return existing
        now = datetime.now(timezone.utc).isoformat()
        update_params = {"sent_at": now}
        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"queued", "delivery_failed"},
            target_status="sent",
            update_params=update_params,
        )

    def mark_completed(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Marks item as completed once consumer confirms successful processing. Idempotent if already sent."""
        existing = self.get_by_id(item_id)
        if existing and existing.get("status") == "sent":
            return existing
        now = datetime.now(timezone.utc).isoformat()
        update_params = {"sent_at": now}
        return self._execute_checked_transition(
            item_id=item_id,
            expected_statuses={"queued", "sent", "delivery_failed"},
            target_status="sent",
            update_params=update_params,
        )

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

    def get_all_items(self) -> List[Dict[str, Any]]:
        """Retrieves all review items from SQLite store."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM review_items ORDER BY created_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def export_to_csv(self, export_path: Any) -> int:
        """Exports review items from SQLite database to a CSV file.

        The CSV file is strictly an export report; all state reads and transitions
        rely solely on the SQLite database as the single source of truth.
        """
        import csv

        dest_path = Path(export_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        items = self.get_all_items()
        if not items:
            fieldnames = [
                "item_id",
                "created_at",
                "updated_at",
                "item_kind",
                "target_agent",
                "status",
                "content_hash",
                "approved_content_hash",
            ]
            with open(dest_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            return 0

        fieldnames = list(items[0].keys())
        with open(dest_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                writer.writerow(item)

        return len(items)
