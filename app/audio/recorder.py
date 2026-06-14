import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
from PySide6.QtCore import QThread, Signal
from app.audit.audit_logger import log_audit_event

class AudioRecorderThread(QThread):
    finished_recording = Signal(str)  # emits the saved wav path
    error_occurred = Signal(str)

    def __init__(self, output_path: str, limit_seconds: int = 60, sample_rate: int = 16000) -> None:
        super().__init__()
        self.output_path = output_path
        self.limit_seconds = limit_seconds
        self.sample_rate = sample_rate
        self.is_recording = False

    def run(self) -> None:
        self.is_recording = True
        log_audit_event("RECORDING_START", "session", f"Recording started, target limit: {self.limit_seconds}s")
        
        try:
            # sounddevice.rec automatically falls back to default system input device
            # if no device parameter is passed.
            duration_samples = int(self.limit_seconds * self.sample_rate)
            
            # Start non-blocking recording
            audio_data = sd.rec(
                duration_samples,
                samplerate=self.sample_rate,
                channels=1,
                dtype=np.int16
            )
            
            # Wait for recording to complete or thread to be stopped
            elapsed = 0.0
            while self.is_recording and elapsed < self.limit_seconds:
                time_step = 0.1
                self.msleep(int(time_step * 1000))
                elapsed += time_step
            
            sd.stop()
            sd.wait()
            
            # Slice audio data if stopped early
            actual_samples = int(elapsed * self.sample_rate)
            if actual_samples < duration_samples:
                audio_data = audio_data[:actual_samples]
                
            # Write WAV file
            wav.write(self.output_path, self.sample_rate, audio_data)
            
            log_audit_event("RECORDING_STOP", "session", f"Recording stopped and saved to {self.output_path}")
            self.finished_recording.emit(self.output_path)
            
        except Exception as e:
            error_msg = str(e)
            log_audit_event("RECORDING_ERROR", "session", f"Recording failed: {error_msg}")
            self.error_occurred.emit(error_msg)
        finally:
            self.is_recording = False

    def stop_recording(self) -> None:
        """Stops the recording loop early."""
        self.is_recording = False
