"""Versioned SQLite database module for authoritative outbound record storage."""

from datetime import datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.audit.audit_logger import log_audit_event
from app.destinations.canonical_json import compute_canonical_content_hash
from app.utils.paths import get_app_data_dir


class IdempotencyConflictError(Exception):
    """Raised when an item_id already exists with a different content_hash."""

    pass


ALLOWED_RELEASE_BASES = {"human_approval", "policy_auto_release", "trusted_auto_release"}
ALLOWED_CLASSIFICATIONS = {"non_sensitive", "internal", "sensitive", "confidential"}


def validate_payload_v2(payload: Dict[str, Any]) -> None:
    """Validates the claimed cvn.outbound_item.v2 payload prior to database transaction.

    Raises:
        ValueError: If any required field fails fail-closed validation.
    """
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary")

    schema_version = payload.get("schema_version")
    if schema_version is None:
        payload["schema_version"] = "cvn.outbound_item.v2"
        schema_version = "cvn.outbound_item.v2"
    elif schema_version != "cvn.outbound_item.v2":
        raise ValueError(
            f"Unsupported schema_version '{schema_version}'. Expected 'cvn.outbound_item.v2'."
        )

    item_id = payload.get("item_id")
    if not item_id or not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("Payload missing valid non-empty item_id string")

    item_kind = payload.get("item_kind")
    if item_kind != "record_only":
        raise ValueError(
            f"RecordDatabase cannot process item_kind '{item_kind}'. Expected 'record_only'."
        )

    target_agent = payload.get("target_agent")
    if not target_agent or not isinstance(target_agent, str) or not target_agent.strip():
        raise ValueError("Payload missing valid non-empty target_agent string")

    source_device_id = payload.get("source_device_id") or payload.get("source_device")
    if not source_device_id or not isinstance(source_device_id, str) or not source_device_id.strip():
        payload["source_device_id"] = "unknown_device"

    created_at = payload.get("created_at")
    if not created_at or not isinstance(created_at, str):
        payload["created_at"] = datetime.now().isoformat()
    else:
        try:
            datetime.fromisoformat(created_at)
        except ValueError:
            raise ValueError(f"Payload created_at '{created_at}' is not a valid ISO 8601 timestamp")

    task = payload.get("task")
    if task is not None and task != {}:
        raise ValueError(
            "record_only payload cannot contain task instructions"
        )

    content = payload.get("content")
    if not isinstance(content, dict):
        raise ValueError("Payload content must be a dictionary")

    title = content.get("title")
    if title is None or not isinstance(title, str) or not title.strip():
        raise ValueError("Payload content.title must be a non-empty string")

    if "recorded_at" in content and content["recorded_at"] is not None:
        rec_at = content["recorded_at"]
        if not isinstance(rec_at, str):
            raise ValueError("content.recorded_at must be an ISO 8601 string")
        try:
            datetime.fromisoformat(rec_at)
        except ValueError:
            raise ValueError(f"content.recorded_at '{rec_at}' is not a valid ISO 8601 timestamp")

    if "duration_seconds" in content and content["duration_seconds"] is not None:
        dur = content["duration_seconds"]
        if not isinstance(dur, (int, float)) or dur < 0:
            raise ValueError("content.duration_seconds must be a non-negative number")

    if "tags" in content and content["tags"] is not None:
        if not isinstance(content["tags"], list):
            raise ValueError("content.tags must be a list")

    if "structured_fields" in content and content["structured_fields"] is not None:
        if not isinstance(content["structured_fields"], dict):
            raise ValueError("content.structured_fields must be a dictionary")

    privacy = payload.get("privacy")
    if privacy is None or not isinstance(privacy, dict):
        payload["privacy"] = {
            "release_basis": "human_approval",
            "automatic_classification": "non_sensitive",
        }
    else:
        if not privacy.get("release_basis"):
            privacy["release_basis"] = "human_approval"
        if not privacy.get("automatic_classification") and not privacy.get("classification"):
            privacy["automatic_classification"] = "non_sensitive"


class RecordDatabase:
    """Authoritative versioned SQLite database for outbound record storage."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = get_app_data_dir() / "outbound_records.db"
        else:
            self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables and run versioned migrations (v1 -> v2)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("BEGIN EXCLUSIVE")
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

            # Schema Version 1 Creation
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
                    "INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)"
                )
                current_version = 1

            # Schema Version 2 Upgrade Migration
            if current_version < 2:
                cursor = conn.execute("PRAGMA table_info(outbound_records)")
                columns = [col[1] for col in cursor.fetchall()]

                # Rename source_device -> source_device_id or add column
                if "source_device" in columns and "source_device_id" not in columns:
                    conn.execute(
                        "ALTER TABLE outbound_records RENAME COLUMN source_device TO source_device_id"
                    )
                elif "source_device_id" not in columns:
                    conn.execute(
                        "ALTER TABLE outbound_records ADD COLUMN source_device_id TEXT"
                    )

                # Add export_status column if missing
                if "export_status" not in columns:
                    conn.execute(
                        "ALTER TABLE outbound_records ADD COLUMN export_status TEXT NOT NULL DEFAULT 'pending'"
                    )

                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version) VALUES (2)"
                )

            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        finally:
            conn.close()

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
        """Validates payload, recomputes & verifies content_hash, and transactionally inserts into SQLite.

        Returns:
            (record_dict, is_new_insert)

        Raises:
            ValueError: If payload fails validation or content_hash mismatches.
            IdempotencyConflictError: If item_id exists with different content_hash.
        """
        # 1. Fail-closed claimed payload validation before opening transaction
        validate_payload_v2(payload)

        item_id = str(payload["item_id"])
        item_kind = str(payload["item_kind"])
        target_agent = str(payload.get("target_agent") or "openclaw")
        content = payload.get("content", {})
        task = payload.get("task")

        # 2. Recompute canonical hash and reject caller mismatch BEFORE opening transaction
        _, computed_hash = compute_canonical_content_hash(
            item_kind=item_kind,
            target_agent=target_agent,
            content=content,
            task=task,
        )

        caller_hash = payload.get("content_hash")
        if caller_hash is not None:
            if not isinstance(caller_hash, str) or not re.match(
                r"^[a-fA-F0-9]{64}$", caller_hash
            ):
                raise ValueError("Caller content_hash must be a 64-character hex string")
            if caller_hash.lower() != computed_hash.lower():
                raise ValueError(
                    f"Payload content_hash '{caller_hash}' does not match recomputed canonical content hash '{computed_hash}'"
                )

        content_hash = computed_hash

        privacy = payload.get("privacy", {})

        # 3. Map production v2 contract fields accurately
        source_device_id = payload.get("source_device_id") or payload.get("source_device")
        recorded_at = content.get("recorded_at") or payload.get("recorded_at")

        dur_val = content.get("duration_seconds")
        if dur_val is None:
            dur_val = content.get("duration") or payload.get("duration_seconds") or payload.get("duration")
        try:
            duration_seconds: Optional[float] = float(dur_val) if dur_val is not None else None
        except (ValueError, TypeError):
            duration_seconds = None

        classification = (
            privacy.get("automatic_classification")
            or privacy.get("classification")
        )
        risk_level = privacy.get("risk_level")
        release_basis = privacy.get("release_basis")

        approval_raw = (
            privacy.get("approval")
            or payload.get("approval_metadata")
            or privacy.get("approval_metadata")
        )
        approval_json = json.dumps(approval_raw) if approval_raw is not None else None

        tags_raw = content.get("tags")
        tags_json = json.dumps(sorted(tags_raw)) if isinstance(tags_raw, list) else None

        sf_raw = content.get("structured_fields")
        sf_json = (
            json.dumps(dict(sorted(sf_raw.items())))
            if isinstance(sf_raw, dict)
            else None
        )

        transcript = content.get("transcript") if "transcript" in content else None
        schema_version = payload.get("schema_version", "cvn.outbound_item.v2")
        created_at = payload.get("created_at", "")
        received_at = payload.get("received_at")
        title = content.get("title", "")
        summary = content.get("summary")
        category = content.get("category")
        safe_processing_ref = (
            payload.get("safe_processing_ref")
            or payload.get("result_reference")
        )

        # 4. Transactional insert or idempotency conflict check
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "SELECT content_hash FROM outbound_records WHERE item_id = ?",
                (item_id,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                existing_hash = existing[0]
                if existing_hash == content_hash:
                    log_audit_event(
                        "RECORD_DB_DUPLICATE",
                        "record_db",
                        f"Item {item_id} already exists with identical hash.",
                    )
                    conn.execute("COMMIT")
                    rec = self.get_record(item_id)
                    return rec if rec is not None else {}, False
                else:
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
                    item_id, content_hash, schema_version, source_device_id,
                    created_at, recorded_at, received_at, duration_seconds,
                    title, summary, category, tags_json, structured_fields_json,
                    transcript, classification, risk_level, release_basis,
                    approval_metadata_json, safe_processing_ref, export_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    item_id,
                    content_hash,
                    schema_version,
                    source_device_id,
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
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        finally:
            conn.close()

        log_audit_event(
            "RECORD_DB_INSERTED",
            "record_db",
            f"Item {item_id} transactionally inserted into SQLite.",
        )
        rec = self.get_record(item_id)
        return rec if rec is not None else {}, True

    def mark_records_exported(self, item_ids: List[str]) -> None:
        """Updates export_status to 'exported' for the given item_ids."""
        if not item_ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" for _ in item_ids)
            conn.execute(
                f"UPDATE outbound_records SET export_status = 'exported' WHERE item_id IN ({placeholders})",
                item_ids,
            )
            conn.commit()

    def get_all_records(self) -> List[Dict[str, Any]]:
        """Returns all records sorted by created_at, item_id for CSV generation."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM outbound_records ORDER BY created_at ASC, item_id ASC"
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_pending_export_records(self) -> List[Dict[str, Any]]:
        """Returns all records with export_status = 'pending'."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM outbound_records WHERE export_status = 'pending' ORDER BY created_at ASC, item_id ASC"
            )
            return [dict(r) for r in cursor.fetchall()]
