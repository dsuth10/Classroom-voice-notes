"""Unit tests for PR 9 — Hardened Record Export and Formula Injection Protection."""

import csv
import json
from pathlib import Path
import pytest

from app.destinations.record_consumer import RecordConsumer, sanitize_csv_field


def test_sanitize_csv_field_formula_prefixes() -> None:
    assert sanitize_csv_field("=1+1") == "'=1+1"
    assert sanitize_csv_field("+2+2") == "'+2+2"
    assert sanitize_csv_field("-SUM(A1)") == "'-SUM(A1)"
    assert sanitize_csv_field("@SUM(B1)") == "'@SUM(B1)"
    assert sanitize_csv_field("\tCMD") == "'\tCMD"
    assert sanitize_csv_field("Normal Text") == "Normal Text"


def test_sanitize_csv_field_control_characters() -> None:
    dirty = "Clean\x00Text\x07With\x1bControls"
    cleaned = sanitize_csv_field(dirty)
    assert cleaned == "CleanTextWithControls"


from app.destinations.outbound_payload_builder import build_outbound_payload_v2


def test_record_consumer_sanitizes_export_fields(tmp_path: Path) -> None:
    export_path = tmp_path / "sanitized_export.csv"
    consumer = RecordConsumer(export_file=export_path)

    payload, _, _ = build_outbound_payload_v2(
        item_id="=CVNI-EXPORT-1",
        source_device_id="dev-alpha-123",
        item_kind="record_only",
        target_agent="openclaw",
        content={
            "title": "=SUM(1+1)",
            "summary": "+Command injection",
            "category": "-category",
            "tags": ["maths", "algebra"],
            "structured_fields": {"b_key": "val2", "a_key": "val1"},
        },
        automatic_classification="non_sensitive",
        risk_level="low",
        release_basis="human_approval",
    )

    result = consumer.process_record(payload)
    assert result["status"] == "exported"

    # Read exported CSV rows
    with open(export_path, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 2  # Header + 1 data row
    data_row = rows[1]

    # item_id, created_at, title, category, summary, tags, structured_fields, release_basis
    assert data_row[0] == "'=CVNI-EXPORT-1"
    assert data_row[2] == "'=SUM(1+1)"
    assert data_row[3] == "'-category"
    assert data_row[4] == "'+Command injection"

    # Structured fields are sorted deterministically: a_key comes before b_key
    assert data_row[6] == '{"a_key": "val1", "b_key": "val2"}'
