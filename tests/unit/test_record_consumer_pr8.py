"""Unit tests for PR 8 — Remote v2 Queue Consumers & Hermes Guard."""

import json
from pathlib import Path
import pytest

from app.destinations.openclaw_adapter import OpenClawAdapter
from app.destinations.record_consumer import RecordConsumer
from app.worker.errors import UnsupportedTargetAgent, UnsupportedContractVersion, InvalidTaskPayload


def test_openclaw_adapter_accepts_v2_payload() -> None:
    adapter = OpenClawAdapter(config={}, gateway_token="test-token")
    v2_task = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-20260801-120000-ABCD",
        "item_kind": "agent_task",
        "target_agent": "openclaw",
        "content": {"title": "Maths Quiz", "summary": "Grade 5 fractions"},
        "task": {"title": "Maths Quiz", "instructions": '{"task_type":"classroom_note.summary"}'},
    }

    adapter.validate_task(v2_task)
    converted = adapter.convert_task(v2_task)
    assert converted["user"] == "cvn-task:CVNI-20260801-120000-ABCD"


def test_openclaw_adapter_rejects_hermes_target_agent() -> None:
    adapter = OpenClawAdapter(config={}, gateway_token="test-token")
    hermes_task = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-20260801-120000-ABCD",
        "item_kind": "agent_task",
        "target_agent": "hermes",
        "content": {"title": "Hermes Note"},
        "task": {"title": "Hermes Note", "instructions": "Do research"},
    }

    with pytest.raises(UnsupportedTargetAgent, match="Hermes target agent is disabled"):
        adapter.validate_task(hermes_task)


def test_record_consumer_v2_export(tmp_path: Path) -> None:
    export_file = tmp_path / "outbound_records.csv"
    consumer = RecordConsumer(export_file=export_file)

    payload = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-REC-200",
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "created_at": "2026-08-01T12:00:00Z",
        "content": {
            "title": "Science Lesson Record",
            "summary": "Photosynthesis discussion",
            "category": "science_note",
            "tags": ["biology", "year5"],
            "structured_fields": {"unit": "plants"},
        },
        "privacy": {"release_basis": "human_approval"},
        "task": None,
    }

    res = consumer.process_record(payload)
    assert res["status"] == "exported"
    assert consumer.is_already_processed("CVNI-REC-200") is True

    # Duplicate submission returns duplicate_skipped
    res_dup = consumer.process_record(payload)
    assert res_dup["status"] == "duplicate_skipped"
