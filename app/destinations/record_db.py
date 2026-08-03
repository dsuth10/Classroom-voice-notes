"""Versioned SQLite database module for authoritative outbound record storage."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.audit.audit_logger import log_audit_event
from app.destinations.canonical_json import compute_canonical_content_hash
from app.utils.paths import get_app_data_dir


class IdempotencyConflictError(Exception):
    """Raised when an item_id already exists with a different content_hash."""

    pass


class RecordDatabase:
    """Authoritative versioned SQLite database for outbound record storage."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = get_app_data_dir() / "outbound_records.db"
        else:
            self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables and run versioned migrations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            cursor = conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            )
            row = cursor.fetchone()
            current_version = row[0] if row and row[0] is not None else 0

            if current_version < 1:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS outbound_records (
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
                    "INSERT INTO schema_migrations (version) VALUES (1)"
                )
            conn.commit()

    def get_record(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single record by item_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM outbound_records WHERE item_id = ?", (item_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    def insert_record(
        self, payload: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool]:
        """Validates payload and transactionally inserts full record into SQLite.

        Returns:
            (record_dict, is_new_insert)

        Raises:
            ValueError: If payload fails validation (e.g. not record_only or contains task).
            IdempotencyConflictError: If item_id exists with different content_hash.
        """
        # Task 4: Validate before opening transaction
        item_id = payload.get("item_id")
        if not item_id or not isinstance(item_id, str):
            raise ValueError("Payload missing valid item_id")

        item_kind = payload.get("item_kind", "")
        if item_kind != "record_only":
            raise ValueError(
                f"RecordDatabase cannot process item_kind '{item_kind}'"
            )

        if payload.get("task") is not None:
            raise ValueError(
                "record_only payload cannot contain task instructions"
            )

        content = payload.get("content", {})
        if not isinstance(content, dict):
            raise ValueError("Payload content must be a dictionary")

        title = content.get("title")
        if title is None:
            title = ""

        # Compute content hash if not provided in payload
        content_hash = payload.get("content_hash")
        if not content_hash:
            _, content_hash = compute_canonical_content_hash(
                item_kind=item_kind,
                target_agent=payload.get("target_agent"),
                content=content,
                task=payload.get("task"),
            )

        privacy = payload.get("privacy", {})
        if not isinstance(privacy, dict):
            privacy = {}

        # Prepare field values
        tags_raw = content.get("tags")
        tags_json = json.dumps(sorted(tags_raw)) if isinstance(tags_raw, list) else None

        sf_raw = content.get("structured_fields")
        sf_json = (
            json.dumps(dict(sorted(sf_raw.items())))
            if isinstance(sf_raw, dict)
            else None
        )

        approval_raw = (
            payload.get("approval_metadata")
            or privacy.get("approval_metadata")
        )
        approval_json = json.dumps(approval_raw) if approval_raw is not None else None

        # Transcript only included if explicitly present in content dict
        transcript = content.get("transcript") if "transcript" in content else None

        schema_version = payload.get("schema_version", "cvn.outbound_item.v2")
        source_device = payload.get("source_device")
        created_at = payload.get("created_at", "")
        recorded_at = payload.get("recorded_at")
        received_at = payload.get("received_at")

        duration = payload.get("duration") or payload.get("duration_seconds")
        try:
            duration_seconds = float(duration) if duration is not None else None
        except (ValueError, TypeError):
            duration_seconds = None

        summary = content.get("summary")
        category = content.get("category")
        classification = privacy.get("classification")
        risk_level = privacy.get("risk_level")
        release_basis = privacy.get("release_basis")
        safe_processing_ref = (
            payload.get("safe_processing_ref")
            or payload.get("result_reference")
        )

        # Task 5: Transactional insert or idempotency conflict check
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "SELECT content_hash FROM outbound_records WHERE item_id = ?",
                (item_id,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                existing_hash = existing[0]
                # Task 6: Same item ID and same content hash -> return existing (idempotent success)
                if existing_hash == content_hash:
                    log_audit_event(
                        "RECORD_DB_DUPLICATE",
                        "record_db",
                        f"Item {item_id} already exists with identical hash.",
                    )
                    rec = self.get_record(item_id)
                    return rec if rec is not None else {}, False
                else:
                    # Task 7: Same item ID and different content hash -> raise conflict
                    log_audit_event(
                        "RECORD_DB_CONFLICT",
                        "record_db",
                        f"Item {item_id} conflict: existing hash {existing_hash} != {content_hash}",
                    )
                    raise IdempotencyConflictError(
                        f"Item '{item_id}' already exists with a different content hash."
                    )

            conn.execute(
                """
                INSERT INTO outbound_records (
                    item_id, content_hash, schema_version, source_device,
                    created_at, recorded_at, received_at, duration_seconds,
                    title, summary, category, tags_json, structured_fields_json,
                    transcript, classification, risk_level, release_basis,
                    approval_metadata_json, safe_processing_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    content_hash,
                    schema_version,
                    source_device,
                    created_at,
                    recorded_at,
                    received_at,
                    duration_seconds,
                    str(title),
                    summary,
                    category,
                    tags_json,
                    sf_json,
                    transcript,
                    classification,
                    risk_level,
                    release_basis,
                    approval_json,
                    safe_processing_ref,
                ),
            )
            conn.commit()

        log_audit_event(
            "RECORD_DB_INSERTED",
            "record_db",
            f"Item {item_id} transactionally inserted into SQLite.",
        )
        rec = self.get_record(item_id)
        return rec if rec is not None else {}, True

    def get_all_records(self) -> List[Dict[str, Any]]:
        """Returns all records sorted by created_at, item_id for CSV generation."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM outbound_records ORDER BY created_at ASC, item_id ASC"
            )
            return [dict(r) for r in cursor.fetchall()]
