import queue
import time
from PySide6.QtCore import QThread, Signal
import numpy as np
from app.commands.engine import VoskCommandEngine
from app.audit.audit_logger import log_audit_event

class VoskCommandWorker(QThread):
    command_detected = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, model_path: str, keywords: list[str], cooldown_seconds: float = 2.0) -> None:
        super().__init__()
        self.model_path = model_path
        self.keywords = keywords
        self.cooldown_seconds = cooldown_seconds
        self.queue: queue.Queue[bytes] = queue.Queue()
        self.is_listening = False
        self.last_command_time = 0.0

    def run(self) -> None:
        self.is_listening = True
        
        try:
            # Instantiate engine inside run to bind Model to QThread context
            engine = VoskCommandEngine(self.model_path, self.keywords)
            log_audit_event("COMMAND_WORKER_START", "commands", f"Vosk command worker started listening for keywords: {self.keywords}")
        except Exception as e:
            err_msg = str(e)
            log_audit_event("COMMAND_WORKER_ERROR", "commands", f"Failed to initialise Vosk engine: {err_msg}")
            self.error_occurred.emit(err_msg)
            self.is_listening = False
            return
            
        while self.is_listening:
            try:
                chunk_bytes = self.queue.get(timeout=0.05)
                
                # Enforce debounce cooldown
                now = time.time()
                if now - self.last_command_time < self.cooldown_seconds:
                    continue
                    
                chunk_samples = np.frombuffer(chunk_bytes, dtype=np.int16)
                command = engine.accept_chunk(chunk_samples)
                if command:
                    self.last_command_time = now
                    log_audit_event("COMMAND_DETECTED", "commands", f"Spoken command detected: '{command}'")
                    self.command_detected.emit(command)
            except queue.Empty:
                continue
            except Exception as e:
                log_audit_event("COMMAND_WORKER_ERROR", "commands", f"Vosk processing error: {e}")
                self.error_occurred.emit(str(e))
                break
                
        self.is_listening = False
        log_audit_event("COMMAND_WORKER_STOP", "commands", "Vosk command worker stopped listening")

    def stop_listening(self) -> None:
        """Stops the listening loop."""
        self.is_listening = False
