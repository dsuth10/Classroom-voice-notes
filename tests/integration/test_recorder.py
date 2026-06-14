from pathlib import Path
from unittest import mock
import numpy as np
import pytest
from typing import Any, Generator
from app.audio.recorder import AudioRecorderThread

@pytest.fixture
def mock_sounddevice() -> Generator[mock.MagicMock, None, None]:
    """Mock sounddevice to simulate recording without a physical microphone."""
    with mock.patch("sounddevice.InputStream") as mock_input:
        # Simulate sounddevice returning audio chunks
        mock_stream = mock.MagicMock()
        mock_input.return_value.__enter__.return_value = mock_stream
        yield mock_stream

def test_recorder_thread_saves_wav(tmp_path: Path, mock_sounddevice: mock.MagicMock) -> None:
    """Verifies that the recorder thread runs and successfully writes a WAV file."""
    output_wav = tmp_path / "test_note.wav"
    
    # Configure mock sounddevice to invoke callback with silent data
    def simulate_callback(self, *args: Any, **kwargs: Any) -> None:
        pass
        
    # Create thread
    recorder = AudioRecorderThread(str(output_wav), limit_seconds=2)
    
    # We mock the sounddevice callback recording to write dummy data
    with mock.patch("sounddevice.rec", return_value=np.zeros((16000, 1), dtype=np.int16)) as mock_rec, \
         mock.patch("sounddevice.wait") as mock_wait, \
         mock.patch("scipy.io.wavfile.write") as mock_wav_write:
         
        recorder.start()
        # Wait for thread to finish
        recorder.wait()
        
        mock_rec.assert_called_once()
        mock_wait.assert_called_once()
        mock_wav_write.assert_called_once()
