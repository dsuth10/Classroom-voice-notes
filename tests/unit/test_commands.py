import pytest
from unittest import mock
import numpy as np
from PySide6.QtWidgets import QApplication
import sys
import time

# Mock vosk before importing engine/worker
sys.modules['vosk'] = mock.MagicMock()

from app.commands.engine import VoskCommandEngine
from app.commands.worker import VoskCommandWorker

@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app

def test_vosk_command_engine() -> None:
    with mock.patch("vosk.KaldiRecognizer") as mock_rec_cls, \
         mock.patch("vosk.Model") as mock_model_cls:
         
        mock_rec = mock.MagicMock()
        mock_rec_cls.return_value = mock_rec
        
        # Test partial result matching
        mock_rec.AcceptWaveform.return_value = False
        mock_rec.PartialResult.return_value = '{"partial": "save"}'
        
        engine = VoskCommandEngine("dummy_model_path", keywords=["save", "cancel"])
        chunk = np.zeros(1280, dtype=np.int16)
        
        # Accept chunk should parse partial result
        res = engine.accept_chunk(chunk)
        assert res == "save"
        mock_rec.AcceptWaveform.assert_called_once()
        mock_rec.PartialResult.assert_called_once()

def test_vosk_worker_cooldown(qapp) -> None:
    with mock.patch("vosk.KaldiRecognizer") as mock_rec_cls, \
         mock.patch("vosk.Model") as mock_model_cls:
         
        mock_rec = mock.MagicMock()
        # Returns "save" on first, "cancel" on second
        mock_rec.AcceptWaveform.return_value = False
        mock_rec.PartialResult.side_effect = ['{"partial": "save"}', '{"partial": "cancel"}']
        mock_rec_cls.return_value = mock_rec
        
        worker = VoskCommandWorker("dummy_model_path", keywords=["save", "cancel"], cooldown_seconds=1.0)
        
        commands = []
        worker.command_detected.connect(commands.append)
        
        # Put 2 chunks
        worker.queue.put(np.zeros(1280, dtype=np.int16).tobytes())
        worker.queue.put(np.zeros(1280, dtype=np.int16).tobytes())
        
        worker.start()
        
        # Process events
        for _ in range(20):
            QApplication.processEvents()
            time.sleep(0.01)
            
        # Cooldown should block the second "cancel" command because 1.0s hasn't passed!
        assert len(commands) == 1
        assert commands[0] == "save"
        
        worker.stop_listening()
        worker.wait()
        QApplication.processEvents()
