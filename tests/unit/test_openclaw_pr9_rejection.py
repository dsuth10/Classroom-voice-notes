"""Unit tests verifying PR 9 OpenClaw adapter rejection of record_only payloads."""

import pytest
from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import InvalidTaskPayload


def test_openclaw_rejects_record_only_payload() -> None:
    adapter = OpenClawAdapter(config={}, gateway_token="test-token")
    payload = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": "CVNI-20260801-123456-ABCD",
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {"title": "Note Title", "summary": "Note Summary"},
        "task": {},
    }

    with pytest.raises(InvalidTaskPayload, match="record_only"):
        adapter.validate_task(payload)

    with pytest.raises(InvalidTaskPayload, match="record_only"):
        adapter.convert_task(payload)
