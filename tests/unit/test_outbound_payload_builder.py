"""Unit tests for outbound_payload_builder.py v2 payload generation and signature refreshing."""
from datetime import datetime, timedelta, timezone
import json
import pytest

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
    secret = "test-hmac-secret-not-for-production"
    t1 = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 2, 12, 5, 0, tzinfo=timezone.utc)

    payload, json_str, _ = build_outbound_payload_v2(
        item_id="CVNI-TEST-003",
        source_device_id="device-001",
        item_kind="record_only",
        target_agent="openclaw",
        content={"title": "Original Title"},
        now_provider=lambda: t1,
    )

    original_content_hash = payload["content_hash"]
    original_idempotency_key = payload["idempotency_key"]
    assert payload["signed_at"] == t1.isoformat()

    # Simulate transport refresh > 5 minutes later with deterministic clock
    refreshed_payload, refreshed_json, refreshed_hash, signature = (
        refresh_transport_signature(json_str, secret, now_provider=lambda: t2)
    )

    assert refreshed_payload["content_hash"] == original_content_hash
    assert refreshed_payload["idempotency_key"] == original_idempotency_key
    assert refreshed_payload["signed_at"] == t2.isoformat()
    assert refreshed_payload["signed_at"] != payload["signed_at"]
    assert refreshed_payload["nonce"] != payload["nonce"]
    assert len(signature) == 64


def test_refresh_transport_signature_rejects_naive_datetime() -> None:
    secret = "test-hmac-secret-not-for-production"
    payload, json_str, _ = build_outbound_payload_v2(
        item_id="CVNI-TEST-004",
        source_device_id="device-001",
        item_kind="record_only",
        target_agent="openclaw",
        content={"title": "Original Title"},
    )
    naive_dt = datetime(2026, 8, 2, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware UTC datetime"):
        refresh_transport_signature(json_str, secret, now_provider=lambda: naive_dt)
