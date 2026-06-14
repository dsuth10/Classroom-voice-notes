import pytest
from unittest import mock
import numpy as np
from PySide6.QtWidgets import QApplication
import sys
import time

# Mock openwakeword model before importing engine/worker
sys.modules['openwakeword'] = mock.MagicMock()
sys.modules['openwakeword.model'] = mock.MagicMock()

from app.wakeword.engine import OpenWakeWordEngine, ManualOnlyEngine
from app.wakeword.worker import WakeWordWorker

@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app

def test_manual_only_engine() -> None:
    engine = ManualOnlyEngine()
    chunk = np.zeros(1280, dtype=np.int16)
    assert engine.predict(chunk) == 0.0
    assert not engine.detect(chunk)

def test_openwakeword_engine_prediction() -> None:
    with mock.patch("openwakeword.model.Model") as mock_model_cls:
        mock_model = mock.MagicMock()
        mock_model.predict.return_value = {"joshua_note": 0.85}
        mock_model_cls.return_value = mock_model
        
        engine = OpenWakeWordEngine("dummy_path.onnx", threshold=0.5)
        chunk = np.zeros(1280, dtype=np.int16)
        
        assert engine.predict(chunk) == 0.85
        assert engine.detect(chunk) is True
        assert mock_model.predict.call_count == 2

def test_wakeword_worker_emits_signal(qapp) -> None:
    with mock.patch("openwakeword.model.Model") as mock_model_cls:
        mock_model = mock.MagicMock()
        mock_model.predict.side_effect = [{"joshua_note": 0.1}, {"joshua_note": 0.9}]
        mock_model_cls.return_value = mock_model
        
        engine = OpenWakeWordEngine("dummy_path.onnx", threshold=0.5)
        worker = WakeWordWorker(engine, phrase="Joshua note", threshold=0.5)
        
        detected_events = []
        errors = []
        worker.wake_word_detected.connect(lambda phrase, score: detected_events.append((phrase, score)))
        worker.error_occurred.connect(errors.append)
        
        # Put 2 silent chunks in worker queue
        chunk_bytes = np.zeros(1280, dtype=np.int16).tobytes()
        worker.queue.put(chunk_bytes)
        worker.queue.put(chunk_bytes)
        
        # Start worker thread
        worker.start()
        
        # Wait a short moment and process Qt events to handle cross-thread signals
        for _ in range(30):
            QApplication.processEvents()
            time.sleep(0.01)
        
        worker.stop_listening()
        worker.wait()
        QApplication.processEvents()
        
        print(f"Errors encountered in worker: {errors}")
        assert not errors
        # Should have detected once (on the second chunk)
        assert len(detected_events) == 1
        assert detected_events[0] == ("Joshua note", 0.9)

