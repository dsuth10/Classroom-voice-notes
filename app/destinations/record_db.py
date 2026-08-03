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


import math

class IdempotencyConflictError(Exception):
    """Raised when an item_id already exists with a different content_hash."""

    pass


ALLOWED_RELEASE_BASES = {
    "automatic_policy",
    "human_approval",
    "trusted_mode",
}

ALLOWED_CLASSIFICATIONS = {
    "non_sensitive",
    "sensitive_pii",
    "safeguarding",
    "medical",
    "sensitive",
}

ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_TARGET_AGENTS = {"openclaw"}


def _require_aware_iso8601(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a timezone-aware ISO 8601 timestamp")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a timezone-aware ISO 8601 timestamp"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")

    return parsed


def validate_payload_v2(payload: Dict[str, Any]) -> None:
    """Validates the claimed cvn.outbound_item.v2 payload prior to database transaction.

    Must be pure and fail-closed. Does not mutate the payload dict.

    Raises:
        ValueError: If any required field fails fail-closed validation.
    """
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary")

    schema_version = payload.get("schema_version")
    if schema_version != "cvn.outbound_item.v2":
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
    if target_agent not in ALLOWED_TARGET_AGENTS:
        raise ValueError(f"Payload target_agent '{target_agent}' must be in {ALLOWED_TARGET_AGENTS}")

    source_device_id = payload.get("source_device_id")
    if not source_device_id or not isinstance(source_device_id, str) or not source_device_id.strip() or source_device_id == "unknown_device":
        raise ValueError("Payload missing valid non-empty source_device_id string")

    created_at = payload.get("created_at")
    _require_aware_iso8601(created_at, "created_at")

    caller_hash = payload.get("content_hash")
    if not isinstance(caller_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", caller_hash):
        raise ValueError("content_hash must be a lowercase 64-character SHA-256 value")

    content = payload.get("content")
    if not isinstance(content, dict):
        raise ValueError("Payload content must be a dictionary")

    privacy = payload.get("privacy")
    if not isinstance(privacy, dict):
        raise ValueError("Payload privacy must be a dictionary")

    task = payload.get("task")
    if task is not None and task != {}:
        raise ValueError("record_only payload cannot contain task instructions")

    # Content validation
    title = content.get("title")
    if title is None or not isinstance(title, str) or not title.strip():
        raise ValueError("Payload content.title must be a non-empty string")

    if "summary" in content and content["summary"] is not None:
        if not isinstance(content["summary"], str):
            raise ValueError("content.summary must be a string")

    if "category" in content and content["category"] is not None:
        if not isinstance(content["category"], str):
            raise ValueError("content.category must be a string")

    if "recorded_at" in content and content["recorded_at"] is not None:
        _require_aware_iso8601(content["recorded_at"], "content.recorded_at")

    if "duration_seconds" in content and content["duration_seconds"] is not None:
        dur = content["duration_seconds"]
        if isinstance(dur, bool) or not isinstance(dur, (int, float)):
            raise ValueError("content.duration_seconds must be a non-negative number")
        if not math.isfinite(dur) or dur < 0:
            raise ValueError("content.duration_seconds must be finite and non-negative")

    if "tags" in content and content["tags"] is not None:
        tags = content["tags"]
        if not isinstance(tags, list):
            raise ValueError("content.tags must be a list")
        if not all(isinstance(t, str) for t in tags):
            raise ValueError("content.tags entries must be strings")

    if "structured_fields" in content and content["structured_fields"] is not None:
        sf = content["structured_fields"]
        if not isinstance(sf, dict):
            raise ValueError("content.structured_fields must be a dictionary")
        if not all(isinstance(k, str) for k in sf.keys()):
            raise ValueError("content.structured_fields keys must be strings")

    if "transcript" in content and content["transcript"] is not None:
        if not isinstance(content["transcript"], str):
            raise ValueError("content.transcript must be a string")

    # Privacy validation
    auto_class = privacy.get("automatic_classification")
    if auto_class not in ALLOWED_CLASSIFICATIONS:
        raise ValueError(f"privacy.automatic_classification '{auto_class}' must be in {ALLOWED_CLASSIFICATIONS}")

    risk = privacy.get("risk_level")
    if risk not in ALLOWED_RISK_LEVELS:
        raise ValueError(f"privacy.risk_level '{risk}' must be in {ALLOWED_RISK_LEVELS}")

    rel_basis = privacy.get("release_basis")
    if rel_basis not in ALLOWED_RELEASE_BASES:
        raise ValueError(f"privacy.release_basis '{rel_basis}' must be in {ALLOWED_RELEASE_BASES}")

    if rel_basis in ("human_approval", "trusted_mode"):
        approval = privacy.get("approval")
        if not isinstance(approval, dict):
            raise ValueError(f"privacy.approval dictionary required for release_basis '{rel_basis}'")

        app_at = approval.get("approved_at")
        _require_aware_iso8601(app_at, "privacy.approval.approved_at")

        app_hash = approval.get("approved_content_hash")
        if not isinstance(app_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", app_hash):
            raise ValueError("privacy.approval.approved_content_hash must be a lowercase 64-character SHA-256 value")

        if app_hash != caller_hash:
            raise ValueError("privacy.approval.approved_content_hash does not match content_hash")

    elif rel_basis == "automatic_policy":
        checks = privacy.get("checks_passed")
        if not isinstance(checks, list) or len(checks) == 0 or not all(isinstance(c, str) for c in checks):
            raise ValueError("privacy.checks_passed must be a non-empty list of strings for automatic_policy")


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
        target_agent = str(payload["target_agent"])
        content = payload["content"]
        task = payload.get("task")

        # 2. Recompute canonical hash and reject caller mismatch BEFORE opening transaction
        _, computed_hash = compute_canonical_content_hash(
            item_kind=item_kind,
            target_agent=target_agent,
            content=content,
            task=task,
        )

        caller_hash = payload["content_hash"]
        if caller_hash != computed_hash:
            raise ValueError("content_hash does not match recomputed canonical content hash")

        content_hash = computed_hash
        privacy = payload["privacy"]

        source_device_id = str(payload["source_device_id"])
        recorded_at = content.get("recorded_at")

        dur_val = content.get("duration_seconds")
        duration_seconds: Optional[float] = float(dur_val) if dur_val is not None else None

        classification = str(privacy["automatic_classification"])
        risk_level = str(privacy["risk_level"])
        release_basis = str(privacy["release_basis"])

        approval_raw = privacy.get("approval")
        approval_json = json.dumps(approval_raw) if approval_raw is not None else None

        tags_raw = content.get("tags")
        tags_json = json.dumps(sorted(tags_raw)) if isinstance(tags_raw, list) else None

        sf_raw = content.get("structured_fields")
        sf_json = (
            json.dumps(dict(sorted(sf_raw.items())))
            if isinstance(sf_raw, dict)
            else None
        )

        transcript = content.get("transcript")
        schema_version = str(payload["schema_version"])
        created_at = str(payload["created_at"])
        received_at = payload.get("received_at")
        title = content["title"]
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
