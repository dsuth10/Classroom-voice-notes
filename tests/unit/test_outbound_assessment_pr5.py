"""Unit tests for PR 5 — Exact Outgoing v2 Content Assessment and Privacy Controls."""

import json
from pathlib import Path
import pytest

from app.ollama_router.policy_gate import PolicyGate
from app.privacy.outbound_assessment import OutboundAssessment
from app.destinations.outbound_routing_service import OutboundRoutingService
from app.destinations.outbound_review_store import OutboundReviewStore
from app.config.settings import SettingsManager


def test_assess_v2_item_clean_payload() -> None:
    gate = PolicyGate()
    assessment = gate.assess_v2_item(
        item_kind="record_only",
        target_agent="openclaw",
        content={
            "title": "Mathematics Homework",
            "summary": "Fractions introductory exercise",
            "transcript": "Class completed page 12.",
            "tags": ["maths", "year5"],
            "structured_fields": {"topic": "fractions"},
        },
    )

    assert isinstance(assessment, OutboundAssessment)
    assert assessment.risk_level == "low"
    assert len(assessment.findings) == 0
    assert assessment.safe_auto_allowed is True
    assert "valid_item_kind" in assessment.checks_passed
    assert "no_contact_details" in assessment.checks_passed
    assert "no_local_file_paths" in assessment.checks_passed


def test_assess_v2_item_privacy_threats_field_attribution() -> None:
    gate = PolicyGate()
    assessment = gate.assess_v2_item(
        item_kind="agent_task",
        target_agent="openclaw",
        content={
            "title": "Contact parent at john.doe@example.com",
            "summary": "Call 0412345678 regarding welfare report",
            "transcript": "Notes stored at C:\\Users\\Teacher\\notes.md",
            "tags": ["urgent"],
            "structured_fields": {"attachment": "audio_sample.wav"},
        },
        task={
            "title": "Follow up",
            "instructions": "Use API key sk-proj-123456789012345678901234567890 to sync",
        },
    )

    assert assessment.risk_level == "high"
    assert assessment.safe_auto_allowed is False

    findings_text = " ".join(assessment.findings)
    assert "content.title: email_address" in findings_text
    assert "content.summary: phone_number" in findings_text
    assert "content.summary: forbidden_term ('welfare')" in findings_text
    assert "content.transcript: local_file_path" in findings_text
    assert "content.structured_fields: audio_extension_found" in findings_text
    assert "task.instructions: credential_secret_found" in findings_text


def test_category_fields_compatibility_mapping(tmp_path: Path) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "review_all")
    review_store = OutboundReviewStore(tmp_path / "review.db")

    service = OutboundRoutingService(settings, review_store=review_store)
    result = service.handle_capture(
        classification={
            "category": "general_note",
            "sensitivity": "non_sensitive",
            "title": "Class Note",
            "category_fields": {"subject": "English"},
        },
        transcript="Spelling test results.",
        note_path=str(tmp_path / "note.md"),
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=15,
    )

    assert result.item_id is not None
    item = review_store.get_by_id(result.item_id)
    assert item is not None
    draft = json.loads(item["draft_json"])
    assert draft["content"]["structured_fields"] == {"subject": "English"}


def test_trusted_mode_pauses_on_v2_high_risk(tmp_path: Path) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "trusted_auto")
    settings.set("external_agent.trusted_pause_on_high_risk", True)
    review_store = OutboundReviewStore(tmp_path / "review.db")

    service = OutboundRoutingService(settings, review_store=review_store)
    result = service.handle_capture(
        classification={
            "category": "general_note",
            "sensitivity": "non_sensitive",
            "title": "Contains path C:\\Secret\\data.txt",
        },
        transcript="Private path discussion.",
        note_path=str(tmp_path / "secret.md"),
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=15,
    )

    assert result.action == "added_to_review_queue"
    item = review_store.get_by_id(result.item_id)
    assert item is not None
    assert item["status"] == "awaiting_review"
    assessment = json.loads(item["assessment_json"])
    assert assessment["risk_level"] == "high"
