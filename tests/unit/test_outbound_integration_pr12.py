"""Comprehensive integration and security failure test suite for PR 12."""

import pytest
from pathlib import Path
from unittest import mock

from app.config.settings import SettingsManager
from app.destinations.outbound_review_store import OutboundReviewStore
from app.destinations.outbound_routing_service import OutboundRoutingService
from app.destinations.record_consumer import RecordConsumer
from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import InvalidTaskPayload


def test_pr12_sharing_off_creates_no_outbound_state(tmp_path: Path) -> None:
    """When sharing_mode is 'off', no outbound review item or outbox record is created."""
    settings_mgr = SettingsManager()
    settings_mgr.config_path = tmp_path / "settings.json"
    settings_mgr.set("external_agent.sharing_mode", "off")

    review_store = OutboundReviewStore(db_path=tmp_path / "review.db")
    routing_svc = OutboundRoutingService(settings_manager=settings_mgr, review_store=review_store)

    classification = {
        "automatic_classification": "non_sensitive",
        "risk_level": "low",
        "findings": [],
        "policy_gate_version": "2.0.0",
        "checks_passed": ["no_credentials_found"],
    }

    result = routing_svc.handle_capture(
        classification=classification,
        transcript="Student transcript text",
        note_path="notes/test.md",
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=10,
    )

    assert result.action == "saved_locally_only"
    assert len(review_store.get_awaiting_review()) == 0


def test_pr12_trusted_high_risk_pauses_for_review(tmp_path: Path) -> None:
    """In trusted_auto mode, high-risk content pauses for human review instead of auto-enqueueing."""
    settings_mgr = SettingsManager()
    settings_mgr.config_path = tmp_path / "settings.json"
    settings_mgr.set("external_agent.sharing_mode", "trusted_auto")

    review_store = OutboundReviewStore(db_path=tmp_path / "review.db")
    routing_svc = OutboundRoutingService(settings_manager=settings_mgr, review_store=review_store)

    classification = {
        "category": "general_note",
        "sensitivity": "sensitive_pii",
        "automatic_classification": "sensitive_pii",
        "risk_level": "high",
        "findings": ["student_pii_detected"],
        "policy_gate_version": "2.0.0",
        "checks_passed": [],
    }

    result = routing_svc.handle_capture(
        classification=classification,
        transcript="Student secret key leaked sk-123456789012345678901234567890",
        note_path="notes/test.md",
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=10,
    )

    assert result.action == "added_to_review_queue"
    awaiting = review_store.get_awaiting_review()
    assert len(awaiting) == 1
    assert awaiting[0]["status"] == "awaiting_review"


from app.destinations.outbound_payload_builder import build_outbound_payload_v2


def test_pr12_record_consumer_idempotency_recovery(tmp_path: Path) -> None:
    """RecordConsumer sqlite sidecar index ensures idempotent re-delivery without row duplication."""
    csv_file = tmp_path / "records.csv"
    consumer = RecordConsumer(export_file=csv_file)

    payload, _, _ = build_outbound_payload_v2(
        item_id="CVNI-20260801-999999-IDEM",
        source_device_id="device-synthetic-01",
        item_kind="record_only",
        target_agent="openclaw",
        content={"title": "Math Note", "summary": "Addition lesson"},
        automatic_classification="non_sensitive",
        risk_level="low",
        release_basis="human_approval",
    )

    res1 = consumer.process_record(payload)
    assert res1["status"] == "exported"

    res2 = consumer.process_record(payload)
    assert res2["status"] == "duplicate_skipped"
