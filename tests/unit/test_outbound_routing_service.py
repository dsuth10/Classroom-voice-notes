"""Unit tests for OutboundRoutingService."""

import json
from pathlib import Path
from unittest import mock

import pytest

from app.config.settings import SettingsManager
from app.destinations.outbound_review_store import OutboundReviewStore
from app.destinations.outbound_routing_service import OutboundRoutingService


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    config_file = tmp_path / "settings.json"
    with mock.patch(
        "app.config.settings.get_config_path", return_value=config_file
    ):
        yield tmp_path


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "ObsidianVault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    return vault_dir


@pytest.fixture
def review_store(tmp_path: Path) -> OutboundReviewStore:
    return OutboundReviewStore(tmp_path / "test_routing_review.db")


def test_routing_mode_off(
    temp_config_dir: Path, review_store: OutboundReviewStore
) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "off")

    service = OutboundRoutingService(settings, review_store=review_store)
    result = service.handle_capture(
        classification={"category": "agent_task", "title": "Clean desks"},
        transcript="Please clean all desks.",
        note_path="/vault/note.md",
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=30,
    )

    assert result.action == "saved_locally_only"
    assert len(review_store.get_awaiting_review()) == 0


def test_routing_mode_safe_auto_allowed(
    temp_config_dir: Path,
    temp_vault: Path,
    review_store: OutboundReviewStore,
) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "safe_auto")
    settings.set("obsidian_vault_path", str(temp_vault))
    settings.set(
        "external_agent.endpoint_url", "https://ref.supabase.co/functions/v1/cvn-submit"
    )
    settings.set("external_agent.source_device_id", "device-001")

    registry_dir = temp_vault / "Classroom Voice Notes"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = registry_dir / "student_registry.json"
    registry_file.write_text(json.dumps({"students": {}, "next_id": 1}), encoding="utf-8")

    service = OutboundRoutingService(settings, review_store=review_store)

    with mock.patch(
        "app.destinations.external_agent_dispatcher.ExternalAgentDispatcher.dispatch"
    ) as mock_dispatch:
        result = service.handle_capture(
            classification={
                "category": "agent_task",
                "sensitivity": "non_sensitive",
                "title": "Clean desks",
            },
            transcript="Please clean all desks.",
            note_path=str(temp_vault / "note.md"),
            recorded_at="2026-08-01T12:00:00Z",
            duration_seconds=30,
            safe_task={
                "title": "Clean desks",
                "instructions": "Ensure desks clean.",
            },
            payload={
                "schema_version": "cvn.agent_task.v1",
                "task": {
                    "title": "Clean desks",
                    "instructions": "Ensure desks clean.",
                },
            },
        )

    assert result.action == "safe_auto_dispatched"
    mock_dispatch.assert_called_once()


def test_routing_mode_review_all(
    temp_config_dir: Path,
    temp_vault: Path,
    review_store: OutboundReviewStore,
) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "review_all")

    note_file = temp_vault / "maths_note.md"
    note_file.write_text("---\ntitle: Maths Note\n---\nSome content", encoding="utf-8")

    service = OutboundRoutingService(settings, review_store=review_store)
    result = service.handle_capture(
        classification={
            "category": "maths_note",
            "sensitivity": "non_sensitive",
            "title": "Fractions Intro",
        },
        transcript="Today we studied fractions.",
        note_path=str(note_file),
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=45,
    )

    assert result.action == "added_to_review_queue"
    assert result.item_id is not None

    awaiting = review_store.get_awaiting_review()
    assert len(awaiting) == 1
    assert awaiting[0]["item_id"] == result.item_id

    # Check note frontmatter updated
    updated_note_content = note_file.read_text(encoding="utf-8")
    assert "external_item_id:" in updated_note_content
    assert "external_state: awaiting_review" in updated_note_content


def test_routing_mode_trusted_auto_low_risk(
    temp_config_dir: Path,
    temp_vault: Path,
    review_store: OutboundReviewStore,
) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "trusted_auto")

    note_file = temp_vault / "general.md"
    note_file.write_text("General note content", encoding="utf-8")

    service = OutboundRoutingService(settings, review_store=review_store)
    result = service.handle_capture(
        classification={
            "category": "general_note",
            "sensitivity": "non_sensitive",
            "title": "General Class Note",
        },
        transcript="Class discussed homework.",
        note_path=str(note_file),
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=30,
    )

    assert result.action == "trusted_auto_queued"
    assert result.item_id is not None

    item = review_store.get_by_id(result.item_id)
    assert item is not None
    assert item["status"] == "approved"
    assert item["approval_method"] == "trusted_mode"


def test_routing_mode_trusted_auto_high_risk_paused(
    temp_config_dir: Path,
    temp_vault: Path,
    review_store: OutboundReviewStore,
) -> None:
    settings = SettingsManager()
    settings.set("external_agent.sharing_mode", "trusted_auto")
    settings.set("external_agent.trusted_pause_on_high_risk", True)

    note_file = temp_vault / "sensitive.md"
    note_file.write_text("Sensitive note", encoding="utf-8")

    service = OutboundRoutingService(settings, review_store=review_store)
    result = service.handle_capture(
        classification={
            "category": "student_note",
            "sensitivity": "student_sensitive",  # High risk
            "title": "Private Student Observation",
        },
        transcript="Private details.",
        note_path=str(note_file),
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=30,
    )

    assert result.action == "added_to_review_queue"
    assert result.item_id is not None

    item = review_store.get_by_id(result.item_id)
    assert item is not None
    assert item["status"] == "awaiting_review"
