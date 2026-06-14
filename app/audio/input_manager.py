import queue
import threading
from typing import Set, Any
import numpy as np
import sounddevice as sd
from app.config.settings import SettingsManager
from app.audit.audit_logger import log_audit_event

class AudioInputManager:
    def __init__(self, settings_manager: SettingsManager) -> None:
        self.settings_manager = settings_manager
        
        self.sample_rate = self.settings_manager.get("audio.sample_rate") or 16000
        self.channels = self.settings_manager.get("audio.channels") or 1
        self.chunk_size = self.settings_manager.get("audio.chunk_size") or 1280
        pre_roll_seconds = self.settings_manager.get("audio.pre_roll_seconds") or 1.5
        
        self.max_pre_roll_bytes = int(pre_roll_seconds * self.sample_rate * 2)
        
        self.pre_roll_lock = threading.Lock()
        self.pre_roll_buffer = bytearray()
        
        self.subscribers_lock = threading.Lock()
        self.subscribers: Set[queue.Queue[bytes]] = set()
        
        self.stream: sd.InputStream | None = None
        self.is_running = False

    def start(self) -> None:
        if self.is_running:
            return
        
        self.is_running = True
        log_audit_event("MICROPHONE_STREAM_START", "audio", "Starting background audio input stream")
        
        try:
            # sounddevice InputStream starts a background C thread for audio capture
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.int16,
                blocksize=self.chunk_size,
                callback=self._audio_callback
            )
            self.stream.start()
        except Exception as e:
            self.is_running = False
            log_audit_event("MICROPHONE_STREAM_ERROR", "audio", f"Failed to start stream: {e}")
            raise e

    def stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        log_audit_event("MICROPHONE_STREAM_STOP", "audio", "Stopping background audio input stream")
        
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                log_audit_event("MICROPHONE_STREAM_ERROR", "audio", f"Error closing stream: {e}")
            self.stream = None

    def subscribe(self, q: queue.Queue[bytes]) -> None:
        with self.subscribers_lock:
            self.subscribers.add(q)
            log_audit_event("SUBSCRIBER_ADD", "audio", "Queue subscribed to audio stream")

    def unsubscribe(self, q: queue.Queue[bytes]) -> None:
        with self.subscribers_lock:
            if q in self.subscribers:
                self.subscribers.remove(q)
                log_audit_event("SUBSCRIBER_REMOVE", "audio", "Queue unsubscribed from audio stream")

    def get_pre_roll(self) -> bytes:
        with self.pre_roll_lock:
            length = min(len(self.pre_roll_buffer), self.max_pre_roll_bytes)
            if length == 0:
                return b""
            return bytes(self.pre_roll_buffer[-length:])

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Lightweight sounddevice callback to append data to pre-roll and publish to subscribers."""
        if not self.is_running:
            return
            
        chunk_bytes = indata.tobytes()
        
        with self.pre_roll_lock:
            self.pre_roll_buffer.extend(chunk_bytes)
            if len(self.pre_roll_buffer) > self.max_pre_roll_bytes * 2:
                self.pre_roll_buffer = self.pre_roll_buffer[-self.max_pre_roll_bytes:]
                
        with self.subscribers_lock:
            for q in self.subscribers:
                try:
                    q.put_nowait(chunk_bytes)
                except queue.Full:
                    pass
