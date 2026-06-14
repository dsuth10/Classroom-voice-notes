import time
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from app.audio.worker import RecorderWorker

def test_recorder_worker_writes_wav(tmp_path: Path) -> None:
    """Verifies that RecorderWorker consumes queue chunks, prepends pre-roll, and writes a valid WAV file."""
    output_wav = tmp_path / "test_note.wav"
    sample_rate = 16000
    
    # 1.5 seconds pre-roll (silent int16 data: 24000 samples = 48000 bytes)
    pre_roll_bytes = bytes(24000 * 2)
    
    # Create worker
    worker = RecorderWorker(str(output_wav), pre_roll_bytes, sample_rate=sample_rate)
    
    # Add dummy audio chunks to queue
    # 2 chunks of 1280 samples each (each chunk is 2560 bytes)
    chunk1 = np.ones(1280, dtype=np.int16).tobytes()
    chunk2 = (np.ones(1280, dtype=np.int16) * 2).tobytes()
    
    worker.queue.put(chunk1)
    worker.queue.put(chunk2)
    
    # Start worker thread
    worker.start()
    
    # Wait briefly for worker to consume chunks
    time.sleep(0.2)
    
    # Stop recording
    worker.stop_recording()
    worker.wait()  # Wait for QThread to finish
    
    # Verify WAV file exists
    assert output_wav.exists()
    
    # Read WAV file and verify samples
    rate, data = wavfile.read(output_wav)
    assert rate == sample_rate
    
    # Expected total samples: 24000 (pre-roll) + 1280 + 1280 = 26560 samples
    assert len(data) == 26560
    
    # Check pre-roll part (first 24000 samples should be 0)
    assert np.all(data[:24000] == 0)
    # Check chunk1 (next 1280 should be 1)
    assert np.all(data[24000:25280] == 1)
    # Check chunk2 (last 1280 should be 2)
    assert np.all(data[25280:] == 2)
