"""Record Consumer - Handles record_only outbound items for export/spreadsheet population."""

import csv
import json
import sqlite3
from pathlib import Path
import re
from typing import Any, Dict, Optional

from app.audit.audit_logger import log_audit_event
from app.utils.paths import get_app_data_dir


def sanitize_csv_field(val: Any) -> str:
    """Sanitizes field value to prevent formula injection and strip ASCII control chars.

    If value begins with '=', '+', '-', '@', '\\t', '\\r', it is prefixed with a single quote.
    """
    if val is None:
        return ""
    s = str(val)

    # Strip non-printable ASCII control characters (excluding \\n and \\t)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)

    # Formula injection protection
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        log_audit_event(
            "RECORD_EXPORT_SANITIZED",
            "record_consumer",
            "Sanitized potential formula prefix from export field.",
        )
        return f"'{s}"
    return s


class RecordConsumer:
    """Consumer for record_only outbound items.

    Populates structured records into export storage idempotently without
    executing agent instructions.

    Idempotency is guaranteed by a SQLite sidecar index. The SQLite INSERT uses
    INSERT OR IGNORE with a UNIQUE item_id constraint, so concurrent writers
    cannot produce duplicate rows. A crash between index insert and CSV append
    leaves an orphaned index row; on re-delivery the row is skipped as duplicate.
    """

    def __init__(self, export_file: Optional[Path] = None) -> None:
        if export_file is None:
            self.export_file = get_app_data_dir() / "outbound_records.csv"
        else:
            self.export_file = export_file
        self._index_file = self.export_file.with_suffix(".db")
        self._init_export_file()
        self._init_index()

    def _init_export_file(self) -> None:
        self.export_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.export_file.exists():
            with open(self.export_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "item_id",
                    "created_at",
                    "title",
                    "category",
                    "summary",
                    "tags",
                    "structured_fields",
                    "release_basis",
                ])

    def _init_index(self) -> None:
        """Create the SQLite sidecar index for idempotency checking."""
        with sqlite3.connect(self._index_file) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exported_items (
                    item_id TEXT PRIMARY KEY,
                    exported_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()

    def is_already_processed(self, item_id: str) -> bool:
        """Returns True if item_id is in the SQLite index (idempotency guard)."""
        with sqlite3.connect(self._index_file) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM exported_items WHERE item_id = ? LIMIT 1", (item_id,)
            )
            return cursor.fetchone() is not None

    def _mark_indexed(self, item_id: str) -> bool:
        """Atomically inserts item_id into the index. Returns False if already present."""
        with sqlite3.connect(self._index_file) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO exported_items (item_id) VALUES (?)", (item_id,)
            )
            conn.commit()
            return cursor.rowcount == 1

    def process_record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        item_id = payload.get("item_id", "")
        item_kind = payload.get("item_kind", "")

        if item_kind != "record_only":
            raise ValueError(
                f"RecordConsumer cannot process item_kind '{item_kind}'"
            )

        if payload.get("task") is not None:
            raise ValueError(
                "record_only payload cannot contain task instructions"
            )

        # Atomic idempotency check via SQLite INSERT OR IGNORE
        if not self._mark_indexed(item_id):
            log_audit_event(
                "RECORD_CONSUMER_DUPLICATE",
                "record_consumer",
                f"Item {item_id} already exported (index duplicate).",
            )
            return {
                "status": "duplicate_skipped",
                "item_id": item_id,
                "export_row_id": item_id,
            }

        content = payload.get("content", {})
        privacy = payload.get("privacy", {})

        title = sanitize_csv_field(content.get("title", ""))
        category = sanitize_csv_field(content.get("category", ""))
        summary = sanitize_csv_field(content.get("summary", ""))

        tags_raw = content.get("tags", [])
        tags_sorted = sorted(tags_raw) if isinstance(tags_raw, list) else []
        tags_str = sanitize_csv_field(json.dumps(tags_sorted))

        sf_raw = content.get("structured_fields", {})
        sf_sorted = (
            dict(sorted(sf_raw.items())) if isinstance(sf_raw, dict) else {}
        )
        sf_str = sanitize_csv_field(json.dumps(sf_sorted))

        release_basis = sanitize_csv_field(privacy.get("release_basis", ""))
        created_at = sanitize_csv_field(payload.get("created_at", ""))
        item_id_clean = sanitize_csv_field(item_id)

        with open(self.export_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                item_id_clean,
                created_at,
                title,
                category,
                summary,
                tags_str,
                sf_str,
                release_basis,
            ])

        log_audit_event(
            "RECORD_CONSUMER_EXPORTED",
            "record_consumer",
            f"Item {item_id} exported to CSV.",
        )
        return {
            "status": "exported",
            "item_id": item_id,
            "export_row_id": item_id,
        }
