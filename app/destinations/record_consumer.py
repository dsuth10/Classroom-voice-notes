"""Record Consumer - Handles record_only outbound items for export/spreadsheet population."""

import csv
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Dict, Optional

from app.audit.audit_logger import log_audit_event
from app.destinations.record_db import RecordDatabase
from app.utils.paths import get_app_data_dir

_export_lock = threading.Lock()


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

    Populates structured records into SQLite database transactionally and
    regenerates CSV export atomically from a consistent database snapshot.
    """

    def __init__(
        self,
        export_file: Optional[Path] = None,
        db_file: Optional[Path] = None,
    ) -> None:
        if export_file is None:
            self.export_file = get_app_data_dir() / "outbound_records.csv"
        else:
            self.export_file = export_file

        if db_file is None:
            db_file = self.export_file.with_suffix(".db")

        self.db = RecordDatabase(db_file)
        self.regenerate_csv()

    def is_already_processed(self, item_id: str) -> bool:
        """Returns True if item_id exists in the authoritative SQLite store."""
        return self.db.get_record(item_id) is not None

    def regenerate_csv(self) -> Path:
        """Atomically regenerates the CSV spreadsheet export from SQLite."""
        with _export_lock:
            records = self.db.get_all_records()
            temp_dir = self.export_file.parent
            temp_dir.mkdir(parents=True, exist_ok=True)

            fd, tmp_path_str = tempfile.mkstemp(
                dir=temp_dir, prefix="outbound_records_", suffix=".tmp"
            )
            tmp_path = Path(tmp_path_str)
            try:
                with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
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
                    for r in records:
                        item_id_clean = sanitize_csv_field(r.get("item_id", ""))
                        created_at_clean = sanitize_csv_field(
                            r.get("created_at", "")
                        )
                        title_clean = sanitize_csv_field(r.get("title", ""))
                        category_clean = sanitize_csv_field(
                            r.get("category", "")
                        )
                        summary_clean = sanitize_csv_field(r.get("summary", ""))
                        tags_clean = sanitize_csv_field(
                            r.get("tags_json") or "[]"
                        )
                        sf_clean = sanitize_csv_field(
                            r.get("structured_fields_json") or "{}"
                        )
                        release_basis_clean = sanitize_csv_field(
                            r.get("release_basis", "")
                        )
                        writer.writerow([
                            item_id_clean,
                            created_at_clean,
                            title_clean,
                            category_clean,
                            summary_clean,
                            tags_clean,
                            sf_clean,
                            release_basis_clean,
                        ])
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, self.export_file)
                return self.export_file
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise e

    def process_record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Transactionally persists record to SQLite and updates CSV export.

        Raises:
            ValueError: If payload fails validation.
            IdempotencyConflictError: If payload has conflicting content_hash for item_id.
        """
        # Validate and insert record in single transaction inside SQLite DB
        record, is_new = self.db.insert_record(payload)
        item_id = payload["item_id"]

        # Attempt CSV export regeneration (Task 15: Export error does not undo durable record)
        try:
            self.regenerate_csv()
        except Exception as exc:
            log_audit_event(
                "RECORD_EXPORT_FAILED",
                "record_consumer",
                f"CSV generation failed for item {item_id}: {exc}",
            )

        if is_new:
            log_audit_event(
                "RECORD_CONSUMER_EXPORTED",
                "record_consumer",
                f"Item {item_id} persisted to SQLite and exported.",
            )
            return {
                "status": "exported",
                "item_id": item_id,
                "export_row_id": item_id,
            }
        else:
            log_audit_event(
                "RECORD_CONSUMER_DUPLICATE",
                "record_consumer",
                f"Item {item_id} already persisted (duplicate skipped).",
            )
            return {
                "status": "duplicate_skipped",
                "item_id": item_id,
                "export_row_id": item_id,
            }
