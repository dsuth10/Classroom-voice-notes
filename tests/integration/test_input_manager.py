import queue
from unittest import mock
import numpy as np
import pytest
from app.config.settings import SettingsManager
from app.audio.input_manager import AudioInputManager

@pytest.fixture
def settings_manager(tmp_path) -> SettingsManager:
    config_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        manager = SettingsManager()
        yield manager

def test_input_manager_stream_distribution(settings_manager) -> None:
    """Verifies that AudioInputManager captures audio and distributes chunks to subscribers."""
    manager = AudioInputManager(settings_manager)
    
    # We mock sounddevice.InputStream to simulate audio callback triggers
    mock_stream_class = mock.MagicMock()
    
    # Capture the callback passed to the mock sounddevice.InputStream
    callback_fn = None
    def mock_init(*args, **kwargs):
        nonlocal callback_fn
        callback_fn = kwargs.get("callback")
        return mock.MagicMock()
        
    with mock.patch("sounddevice.InputStream", side_effect=mock_init) as mock_input:
        manager.start()
        
        assert mock_input.called
        assert callback_fn is not None
        
        # Subscribe a test queue
        q: queue.Queue[bytes] = queue.Queue()
        manager.subscribe(q)
        
        # Simulate sounddevice callback triggering with 1280 samples of silent int16 data (2560 bytes)
        chunk_samples = 1280
        silent_data = np.zeros((chunk_samples, 1), dtype=np.int16)
        
        # Invoke the callback
        callback_fn(silent_data, chunk_samples, None, None)
        
        # Verify the queue received the chunk
        assert not q.empty()
        data = q.get(timeout=1.0)
        assert len(data) == chunk_samples * 2  # 16-bit mono
        
        # Unsubscribe
        manager.unsubscribe(q)
        
        # Trigger again
        callback_fn(silent_data, chunk_samples, None, None)
        assert q.empty()
        
        manager.stop()

def test_input_manager_pre_roll(settings_manager) -> None:
    """Verifies that the pre-roll buffer maintains the last 1.5s of audio."""
    manager = AudioInputManager(settings_manager)
    
    callback_fn = None
    def mock_init(*args, **kwargs):
        nonlocal callback_fn
        callback_fn = kwargs.get("callback")
        return mock.MagicMock()
        
    with mock.patch("sounddevice.InputStream", side_effect=mock_init):
        manager.start()
        
        chunk_samples = 1280
        silent_data = np.zeros((chunk_samples, 1), dtype=np.int16)
        
        # Trigger callback multiple times to fill pre-roll
        # 1.5 seconds at 16000 Hz = 24000 samples = 48000 bytes
        # Each chunk is 1280 samples. 20 chunks = 25600 samples
        for _ in range(25):
            callback_fn(silent_data, chunk_samples, None, None)
            
        pre_roll = manager.get_pre_roll()
        assert len(pre_roll) == 24000 * 2  # exactly 1.5 seconds of 16-bit mono (48000 bytes)
        
        manager.stop()
