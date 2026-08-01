"""Record Consumer - Handles record_only outbound items for export/spreadsheet population."""

import csv
import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.audit.audit_logger import log_audit_event
from app.utils.paths import get_app_data_dir


class RecordConsumer:
    """Consumer for record_only outbound items.

    Populates structured records into export storage idempotently without
    executing agent instructions.
    """

    def __init__(self, export_file: Optional[Path] = None) -> None:
        if export_file is None:
            self.export_file = get_app_data_dir() / "outbound_records.csv"
        else:
            self.export_file = export_file
        self._init_export_file()

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

    def is_already_processed(self, item_id: str) -> bool:
        if not self.export_file.exists():
            return False
        with open(self.export_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            for row in reader:
                if row and row[0] == item_id:
                    return True
        return False

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

        if self.is_already_processed(item_id):
            log_audit_event(
                "RECORD_CONSUMER_DUPLICATE",
                "record_consumer",
                f"Item {item_id} already exported.",
            )
            return {
                "status": "duplicate_skipped",
                "item_id": item_id,
                "export_row_id": item_id,
            }

        content = payload.get("content", {})
        privacy = payload.get("privacy", {})

        title = content.get("title", "")
        category = content.get("category", "")
        summary = content.get("summary", "")
        tags = json.dumps(content.get("tags", []))
        structured_fields = json.dumps(content.get("structured_fields", {}))
        release_basis = privacy.get("release_basis", "")
        created_at = payload.get("created_at", "")

        with open(self.export_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                item_id,
                created_at,
                title,
                category,
                summary,
                tags,
                structured_fields,
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
