import queue
from typing import Optional
from PySide6.QtCore import QThread, Signal
import numpy as np
from app.wakeword.engine import OpenWakeWordEngine, ManualOnlyEngine, WakeEngine
from app.audit.audit_logger import log_audit_event

class WakeWordWorker(QThread):
    wake_word_detected = Signal(str, float)  # emits (phrase, score)
    error_occurred = Signal(str)

    def __init__(
        self,
        engine: WakeEngine,
        phrase: str = "Joshua note",
        threshold: float = 0.5,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.phrase = phrase
        self.threshold = threshold
        self.queue: queue.Queue[bytes] = queue.Queue()
        self.is_listening = False

    def run(self) -> None:
        self.is_listening = True
        log_audit_event("WAKEWORD_WORKER_START", "wakeword", f"Wake word worker started listening for '{self.phrase}'")

        while self.is_listening:
            try:
                chunk_bytes = self.queue.get(timeout=0.05)
                chunk_samples = np.frombuffer(chunk_bytes, dtype=np.int16)
                if len(chunk_samples) != 1280:
                    continue  # openWakeWord expects exactly 1280 samples

                score = self.engine.predict(chunk_samples)
                if score >= self.threshold:
                    log_audit_event("WAKEWORD_HIT", "wakeword", f"Wake word detected '{self.phrase}' with score {score}")
                    self.wake_word_detected.emit(self.phrase, score)
            except queue.Empty:
                continue
            except Exception as e:
                log_audit_event("WAKEWORD_WORKER_ERROR", "wakeword", f"Inference error: {e}")
                self.error_occurred.emit(str(e))
                break

        self.is_listening = False
        log_audit_event("WAKEWORD_WORKER_STOP", "wakeword", "Wake word worker stopped listening")

    def stop_listening(self) -> None:
        """Stops the listening loop."""
        self.is_listening = False
