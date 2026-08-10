from unittest.mock import MagicMock
from app.controller import AppController
from app.wakeword.engine import ManualOnlyEngine

def test_manual_only_engine_selected_when_configured(tmp_path, monkeypatch):
    mock_settings = MagicMock()
    mock_settings.get.side_effect = lambda key, default=None: {
        "obsidian_vault_path": str(tmp_path / "vault"),
        "wake_word.enabled": True,
        "wake_word.engine": "manual_only",
        "wake_word.model_path": "",
        "wake_word.phrase": "Joshua note",
        "wake_word.threshold": 0.5,
    }.get(key, default)
    mock_settings.external_sharing_enabled.return_value = False

    # Prevent actual audio input stream thread from starting
    monkeypatch.setattr("app.audio.input_manager.AudioInputManager.start", lambda self: None)
    monkeypatch.setattr("app.audio.input_manager.AudioInputManager.stop", lambda self: None)

    controller = AppController(mock_settings)
    assert controller.wakeword_worker is not None
    assert isinstance(controller.wakeword_worker.engine, ManualOnlyEngine)
    controller.cleanup()

def test_engine_falls_back_to_manual_only_on_error(tmp_path, monkeypatch):
    mock_settings = MagicMock()
    mock_settings.get.side_effect = lambda key, default=None: {
        "obsidian_vault_path": str(tmp_path / "vault"),
        "wake_word.enabled": True,
        "wake_word.engine": "openwakeword",
        "wake_word.model_path": "non_existent.onnx",
        "wake_word.phrase": "Joshua note",
        "wake_word.threshold": 0.5,
    }.get(key, default)
    mock_settings.external_sharing_enabled.return_value = False

    monkeypatch.setattr("app.audio.input_manager.AudioInputManager.start", lambda self: None)
    monkeypatch.setattr("app.audio.input_manager.AudioInputManager.stop", lambda self: None)

    # Force OpenWakeWordEngine to raise exception
    def mock_openwakeword(*args, **kwargs):
        raise RuntimeError("ONNX file not found")
    monkeypatch.setattr("app.wakeword.engine.OpenWakeWordEngine", mock_openwakeword)

    controller = AppController(mock_settings)
    assert controller.wakeword_worker is not None
    assert isinstance(controller.wakeword_worker.engine, ManualOnlyEngine)
    controller.cleanup()
