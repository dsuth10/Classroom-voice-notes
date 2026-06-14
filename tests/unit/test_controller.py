import pytest
from unittest import mock
from PySide6.QtWidgets import QApplication
import sys

from app.config.settings import SettingsManager
from app.controller import AppController

@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app

@pytest.fixture
def settings_manager(tmp_path) -> SettingsManager:
    config_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        manager = SettingsManager()
        manager.set("recording.hard_cap_seconds", 60)
        yield manager

@pytest.fixture(autouse=True)
def mock_audio_components():
    """Autouse fixture to mock AudioInputManager, RecorderWorker, WakeWordWorker, and VoskCommandWorker."""
    with mock.patch("app.controller.AudioInputManager") as mock_input_manager_cls, \
         mock.patch("app.audio.worker.RecorderWorker") as mock_recorder_worker_cls, \
         mock.patch("app.wakeword.worker.WakeWordWorker") as mock_wakeword_worker_cls, \
         mock.patch("app.commands.worker.VoskCommandWorker") as mock_command_worker_cls:
        
        mock_input = mock.MagicMock()
        mock_input.sample_rate = 16000
        mock_input.get_pre_roll.return_value = b"preroll"
        mock_input_manager_cls.return_value = mock_input
        
        mock_worker = mock.MagicMock()
        mock_finished = mock.MagicMock()
        mock_error = mock.MagicMock()
        mock_worker.finished_recording = mock_finished
        mock_worker.error_occurred = mock_error
        mock_recorder_worker_cls.return_value = mock_worker
        
        mock_wake_worker = mock.MagicMock()
        mock_wakeword_worker_cls.return_value = mock_wake_worker
        
        mock_cmd_worker = mock.MagicMock()
        mock_command_worker_cls.return_value = mock_cmd_worker
        
        yield mock_input, mock_worker, mock_wake_worker, mock_cmd_worker

def test_controller_initial_state(qapp, settings_manager) -> None:
    controller = AppController(settings_manager)
    assert controller.state == "IDLE_LISTENING"
    assert controller.audio_input_manager.start.called

def test_controller_recording_transitions(qapp, settings_manager, mock_audio_components) -> None:
    controller = AppController(settings_manager)
    mock_input, mock_worker, mock_wake_worker, mock_cmd_worker = mock_audio_components
    
    states = []
    controller.state_changed.connect(states.append)
    
    controller.start_recording()
    assert controller.state == "RECORDING"
    assert controller.recording_timer.isActive()
    assert controller.elapsed_timer.isActive()
    assert mock_input.subscribe.called
    assert mock_worker.start.called
    
    controller.stop_and_save()
    assert controller.state == "TRANSCRIBING"
    assert not controller.recording_timer.isActive()
    assert not controller.elapsed_timer.isActive()
    assert mock_input.unsubscribe.called
    assert mock_worker.stop_recording.called
    
    # Simulate worker finishing compilation
    # Connect a slot to check if state transitions to IDLE_LISTENING after finished
    controller._on_recording_finished("dummy.wav")
    assert controller.state == "IDLE_LISTENING"
    assert controller.recorder_worker is None

def test_controller_cancel_recording(qapp, settings_manager, mock_audio_components) -> None:
    controller = AppController(settings_manager)
    mock_input, mock_worker, mock_wake_worker, mock_cmd_worker = mock_audio_components
    
    controller.start_recording()
    assert controller.state == "RECORDING"
    
    controller.cancel_recording()
    assert controller.state == "IDLE_LISTENING"
    assert not controller.recording_timer.isActive()
    assert not controller.elapsed_timer.isActive()
    assert mock_input.unsubscribe.called
    assert mock_worker.stop_recording.called
    
    # Simulate cancelled finishing
    controller._on_recording_finished("dummy.wav")
    assert controller.state == "IDLE_LISTENING"
    assert controller.recorder_worker is None

def test_controller_recording_timeout(qapp, settings_manager, mock_audio_components) -> None:
    controller = AppController(settings_manager)
    mock_input, mock_worker, mock_wake_worker, mock_cmd_worker = mock_audio_components
    controller.start_recording()
    
    limit_reached_called = False
    def on_limit_reached():
        nonlocal limit_reached_called
        limit_reached_called = True
        
    controller.recording_limit_reached.connect(on_limit_reached)
    
    controller._on_recording_timeout()
    assert limit_reached_called
    assert controller.state == "TRANSCRIBING"

def test_controller_reload_settings(qapp, settings_manager, mock_audio_components) -> None:
    controller = AppController(settings_manager)
    mock_input, mock_worker, mock_wake_worker, mock_cmd_worker = mock_audio_components
    
    # We should have started the wake word worker on init if it's enabled
    assert controller.wakeword_worker is not None
    
    # Let's change settings to disable wake word
    settings_manager.set("wake_word.enabled", False)
    
    controller.reload_settings()
    
    # After reload, the wake word worker should be stopped/removed
    assert controller.wakeword_worker is None
