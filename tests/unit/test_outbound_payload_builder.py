"""Unit tests for outbound_payload_builder.py v2 payload generation and signature refreshing."""
import json
from datetime import datetime, timedelta, timezone
from app.destinations.outbound_payload_builder import (
    build_outbound_payload_v2,
    refresh_transport_signature,
)


def test_build_outbound_payload_v2_record_only() -> None:
    payload, json_str, payload_hash = build_outbound_payload_v2(
        item_id="CVNI-TEST-001",
        source_device_id="device-001",
        item_kind="record_only",
        target_agent="openclaw",
        content={
            "title": "Maths Reflection",
            "summary": "Fractions lesson overview",
            "transcript": None,
            "category": "maths_note",
            "tags": ["fractions"],
            "structured_fields": {},
        },
        automatic_classification="non_sensitive",
        risk_level="low",
        release_basis="human_approval",
    )

    assert payload["schema_version"] == "cvn.outbound_item.v2"
    assert payload["item_id"] == "CVNI-TEST-001"
    assert payload["item_kind"] == "record_only"
    assert payload["task"] is None
    assert payload["privacy"]["release_basis"] == "human_approval"
    assert len(payload_hash) == 64


def test_build_outbound_payload_v2_agent_task() -> None:
    task = {
        "title": "Analyze Code",
        "instructions": "Review Python module",
        "priority": "normal",
    }
    payload, json_str, payload_hash = build_outbound_payload_v2(
        item_id="CVNI-TEST-002",
        source_device_id="device-001",
        item_kind="agent_task",
        target_agent="hermes",
        content={"title": "Code Review", "summary": "Review task"},
        task=task,
        automatic_classification="non_sensitive",
        risk_level="low",
        release_basis="trusted_mode",
    )

    assert payload["schema_version"] == "cvn.outbound_item.v2"
    assert payload["item_kind"] == "agent_task"
    assert payload["task"] == task
    assert payload["privacy"]["release_basis"] == "trusted_mode"


def test_refresh_transport_signature_preserves_content_hash() -> None:
    secret = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    payload, json_str, _ = build_outbound_payload_v2(
        item_id="CVNI-TEST-003",
        source_device_id="device-001",
        item_kind="record_only",
        target_agent="openclaw",
        content={"title": "Original Title"},
    )

    original_content_hash = payload["content_hash"]
    original_idempotency_key = payload["idempotency_key"]

    # Simulate transport refresh > 5 minutes later
    refreshed_payload, refreshed_json, refreshed_hash, signature = (
        refresh_transport_signature(json_str, secret)
    )

    assert refreshed_payload["content_hash"] == original_content_hash
    assert refreshed_payload["idempotency_key"] == original_idempotency_key
    assert refreshed_payload["signed_at"] != payload["signed_at"]
    assert refreshed_payload["nonce"] != payload["nonce"]
    assert len(signature) == 64
