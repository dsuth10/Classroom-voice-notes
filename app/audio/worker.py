import queue
from PySide6.QtCore import QThread, Signal
import numpy as np
import scipy.io.wavfile as wav

class RecorderWorker(QThread):
    finished_recording = Signal(str)  # emits saved wav path
    error_occurred = Signal(str)

    def __init__(self, output_path: str, pre_roll_data: bytes, sample_rate: int = 16000) -> None:
        super().__init__()
        self.output_path = output_path
        self.pre_roll_data = pre_roll_data
        self.sample_rate = sample_rate
        self.queue: queue.Queue[bytes] = queue.Queue()
        self.is_recording = False

    def run(self) -> None:
        self.is_recording = True
        # Initialise buffer with pre-roll data
        buffer = bytearray(self.pre_roll_data)
        
        try:
            while self.is_recording:
                try:
                    # Non-blocking get with timeout to regularly check is_recording status
                    chunk = self.queue.get(timeout=0.05)
                    buffer.extend(chunk)
                except queue.Empty:
                    continue
            
            # Process remaining chunks in the queue after recording was stopped
            while not self.queue.empty():
                try:
                    buffer.extend(self.queue.get_nowait())
                except queue.Empty:
                    break
            
            # Convert accumulated buffer to numpy int16 mono data
            audio_data = np.frombuffer(buffer, dtype=np.int16)
            
            # Write WAV file
            wav.write(self.output_path, self.sample_rate, audio_data)
            self.finished_recording.emit(self.output_path)
            
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.is_recording = False

    def stop_recording(self) -> None:
        """Stops the recording loop."""
        self.is_recording = False
