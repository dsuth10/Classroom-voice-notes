import sys
from pathlib import Path
from unittest import mock
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from app.config.settings import SettingsManager
from app.ui.main_window import MainWindow

@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(sys.argv)
    return app

def test_main_window_loads_settings(qapp: QApplication, tmp_path: Path) -> None:
    """Verifies that the Settings UI displays values from settings_manager correctly."""
    settings_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=settings_file):
        manager = SettingsManager()
        manager.set("obsidian_vault_path", "C:/TestVault")
        manager.set("recording.hard_cap_seconds", 45)
        manager.set("wake_word.phrase", "Hello class")
        
        window = MainWindow(manager)
        assert window.vault_edit.text() == "C:/TestVault"
        assert window.limit_spin.value() == 45
        assert window.wake_phrase_edit.text() == "Hello class"
        window.close()

def test_main_window_saves_settings_valid_models(qapp: QApplication, tmp_path: Path) -> None:
    """Verifies that settings are saved successfully when model paths exist."""
    settings_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=settings_file), \
         mock.patch("pathlib.Path.exists", return_value=True), \
         mock.patch("pathlib.Path.is_dir", return_value=True), \
         mock.patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
         
        manager = SettingsManager()
        window = MainWindow(manager)
        
        window.vault_edit.setText("C:/ValidVault")
        window.wake_enabled_chk.setChecked(True)
        window.wake_engine_combo.setCurrentText("openwakeword")
        window.wake_model_edit.setText("C:/models/joshua.onnx")
        
        window.cmd_enabled_chk.setChecked(True)
        window.cmd_model_edit.setText("C:/models/vosk")
        window.cmd_keywords_edit.setText("save, cancel")
        
        window.save_all()
        
        assert manager.get("obsidian_vault_path") == "C:/ValidVault"
        assert manager.get("wake_word.engine") == "openwakeword"
        assert manager.get("wake_word.enabled") is True
        assert manager.get("wake_word.model_path") == "C:/models/joshua.onnx"
        assert manager.get("spoken_commands.enabled") is True
        assert manager.get("spoken_commands.model_path") == "C:/models/vosk"
        assert manager.get("spoken_commands.grammar_keywords") == ["save", "cancel"]
        
        mock_info.assert_called_once()
        window.close()

def test_main_window_saves_settings_missing_wakeword_fallback(qapp: QApplication, tmp_path: Path) -> None:
    """Verifies fallback choice to manual_only when wake word model is missing."""
    settings_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=settings_file), \
         mock.patch("pathlib.Path.exists", return_value=False), \
         mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes) as mock_question, \
         mock.patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
         
        manager = SettingsManager()
        window = MainWindow(manager)
        
        window.vault_edit.setText("C:/ValidVault")
        window.wake_enabled_chk.setChecked(True)
        window.wake_engine_combo.setCurrentText("openwakeword")
        window.wake_model_edit.setText("C:/missing/joshua.onnx")
        
        window.save_all()
        
        # Should have fallback to manual_only because user selected Yes
        assert manager.get("wake_word.engine") == "manual_only"
        assert manager.get("wake_word.enabled") is False
        assert manager.get("obsidian_vault_path") == "C:/ValidVault"
        
        mock_question.assert_called_once()
        mock_info.assert_called_once()
        window.close()

def test_main_window_saves_settings_missing_vosk_cancel(qapp: QApplication, tmp_path: Path) -> None:
    """Verifies that cancel on missing Vosk model does not save settings."""
    settings_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=settings_file), \
         mock.patch("pathlib.Path.exists", return_value=True), \
         mock.patch("pathlib.Path.is_dir", return_value=False), \
         mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as mock_question, \
         mock.patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
         
        manager = SettingsManager()
        window = MainWindow(manager)
        
        window.vault_edit.setText("C:/OldVault")
        manager.set("obsidian_vault_path", "C:/OldVault")
        
        # Modify inputs in UI but cancel due to missing Vosk
        window.vault_edit.setText("C:/NewVault")
        window.cmd_enabled_chk.setChecked(True)
        window.cmd_model_edit.setText("C:/missing/vosk")
        
        window.save_all()
        
        # Config should NOT be saved
        assert manager.get("obsidian_vault_path") == "C:/OldVault"
        mock_question.assert_called_once()
        mock_info.assert_not_called()
        window.close()

def test_main_window_reloads_controller(qapp: QApplication, tmp_path: Path) -> None:
    """Verifies that MainWindow calls reload_settings on the controller upon saving settings."""
    settings_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=settings_file), \
         mock.patch("pathlib.Path.exists", return_value=True), \
         mock.patch("pathlib.Path.is_dir", return_value=True), \
         mock.patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
         
        manager = SettingsManager()
        mock_controller = mock.MagicMock()
        window = MainWindow(manager, controller=mock_controller)
        
        window.vault_edit.setText("C:/ValidVault")
        window.wake_enabled_chk.setChecked(False)
        window.cmd_enabled_chk.setChecked(False)
        
        window.save_all()
        
        mock_controller.reload_settings.assert_called_once()
        window.close()
