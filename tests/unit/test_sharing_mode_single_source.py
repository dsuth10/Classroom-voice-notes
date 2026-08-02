"""Unit tests for PR 2: Sharing mode as single source of truth."""

import json
from pathlib import Path
from unittest import mock
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config.settings import SettingsManager, DEFAULT_SETTINGS
from app.destinations.outbound_routing_service import OutboundRoutingService
from app.destinations.telegram_dispatcher import TelegramDispatcher
from app.destinations.outbound_review_store import OutboundReviewStore
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def temp_settings(tmp_path: Path) -> SettingsManager:
    config_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        manager = SettingsManager()
        manager.config_path = config_file
        manager.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        manager.save_settings(manager.settings)
        return manager


def test_settings_migration_matrix(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        # Case 1: legacy enabled: true, no sharing_mode -> safe_auto
        config_file.write_text(json.dumps({"external_agent": {"enabled": True}}), encoding="utf-8")
        sm = SettingsManager()
        assert sm.external_sharing_mode() == "safe_auto"
        assert sm.external_sharing_enabled() is True

        # Case 2: legacy enabled: false, no sharing_mode -> off
        config_file.write_text(json.dumps({"external_agent": {"enabled": False}}), encoding="utf-8")
        sm = SettingsManager()
        assert sm.external_sharing_mode() == "off"
        assert sm.external_sharing_enabled() is False

        # Case 3: existing valid mode wins over legacy enabled flag
        config_file.write_text(json.dumps({"external_agent": {"enabled": True, "sharing_mode": "review_all"}}), encoding="utf-8")
        sm = SettingsManager()
        assert sm.external_sharing_mode() == "review_all"

        # Case 4: invalid mode fails closed to off
        config_file.write_text(json.dumps({"external_agent": {"sharing_mode": "invalid_super_mode"}}), encoding="utf-8")
        sm = SettingsManager()
        assert sm.external_sharing_mode() == "off"
        assert sm.external_sharing_enabled() is False


def test_stable_source_device_id_generation(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    config_file.write_text(json.dumps({"external_agent": {"source_device_id": ""}}), encoding="utf-8")
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        sm = SettingsManager()

        device_id = sm.get("external_agent.source_device_id")
        assert device_id != ""
        assert device_id.startswith("cvn-device-")


@pytest.mark.parametrize("mode,expected_action", [
    ("off", "saved_locally_only"),
    ("safe_auto", "saved_locally_only"),  # for general_note non_sensitive without task
    ("review_all", "added_to_review_queue"),
    ("trusted_auto", "trusted_auto_queued"),
])
def test_outbound_routing_modes(temp_settings: SettingsManager, tmp_path: Path, mode: str, expected_action: str) -> None:
    temp_settings.set("external_agent.sharing_mode", mode)
    review_store = OutboundReviewStore(tmp_path / "test_routing.db")
    service = OutboundRoutingService(temp_settings, review_store=review_store)

    classification = {"category": "general_note", "sensitivity": "non_sensitive"}
    result = service.handle_capture(
        classification=classification,
        transcript="Test transcript",
        note_path="/notes/test.md",
        recorded_at="2026-08-01T12:00:00Z",
        duration_seconds=30,
    )
    assert result.action == expected_action


def test_telegram_dispatch_disabled_when_off(temp_settings: SettingsManager) -> None:
    temp_settings.set("external_agent.sharing_mode", "off")
    temp_settings.set("agents.telegram_token", "dummy_token")
    temp_settings.set("agents.agents.openclaw.chat_id", "123456")

    dispatcher = TelegramDispatcher(temp_settings)
    success = dispatcher.dispatch("Test transcript", {"category": "agent_task"}, "/path/test.md")
    assert success is False

    raw_success = dispatcher.send_raw_message("Test message", agent="openclaw")
    assert raw_success is False


def test_main_window_trusted_mode_cancellation(qapp: QApplication, temp_settings: SettingsManager, monkeypatch: pytest.MonkeyPatch) -> None:
    temp_settings.set("external_agent.sharing_mode", "off")
    window = MainWindow(temp_settings)

    # Simulate user rejecting trusted_auto modal prompt
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    trusted_idx = window.sharing_mode_combo.findData("trusted_auto")
    window.sharing_mode_combo.setCurrentIndex(trusted_idx)

    # Selection should revert to 'off'
    assert window.sharing_mode_combo.currentData() == "off"


def test_main_window_save_sharing_mode(
    qapp: QApplication, temp_settings: SettingsManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    window = MainWindow(temp_settings)
    review_idx = window.sharing_mode_combo.findData("review_all")
    window.sharing_mode_combo.setCurrentIndex(review_idx)
    window.include_transcript_chk.setChecked(True)
    window.default_kind_combo.setCurrentText("record_only")
    window.target_agent_combo.setCurrentText("openclaw")

    window.save_all()

    assert temp_settings.external_sharing_mode() == "review_all"
    assert temp_settings.get("external_agent.include_full_transcript") is True
    assert temp_settings.get("external_agent.default_item_kind") == "record_only"
    assert temp_settings.get("external_agent.target_agent_default") == "openclaw"
