import json
import os
from pathlib import Path
from unittest.mock import MagicMock
from app.transcription.worker import PipelineWorker

from app.utils.paths import get_failed_audio_dir

def test_worker_preserves_audio_on_exception(tmp_path, monkeypatch):
    # Setup test WAV file
    temp_dir = tmp_path / "temp_audio"
    temp_dir.mkdir()
    wav_path = temp_dir / "test_recording.wav"
    wav_path.write_bytes(b"RIFF dummy audio data")
    
    # Mock settings manager
    mock_settings = MagicMock()
    mock_settings.get.side_effect = lambda key, default=None: {
        "obsidian_vault_path": str(tmp_path / "vault"),
        "whisper_bin_path": "invalid_whisper.exe",
        "whisper_model_path": "invalid_model.bin",
    }.get(key, default)
    
    # Mock paths
    failed_dir = tmp_path / "failed_recordings"
    monkeypatch.setattr("app.utils.paths.get_failed_audio_dir", lambda: failed_dir)
    
    worker = PipelineWorker(
        wav_path=str(wav_path),
        settings_manager=mock_settings,
        duration_seconds=10.0
    )

    
    # Force worker.run to raise exception inside transcriber
    async def mock_transcribe(*args, **kwargs):
        raise RuntimeError("Simulated Ollama / Transcribe error")
        
    monkeypatch.setattr("app.transcription.transcriber.WhisperTranscriber.transcribe", mock_transcribe)
    
    monkeypatch.setattr("app.transcription.worker.log_audit_event", lambda event, source, detail: print(f"AUDIT LOG: {event} | {source} | {detail}"))
    
    # Execute worker
    worker.run()

    
    # Original WAV should no longer be in temp dir
    assert not wav_path.exists()
    
    # WAV and error metadata JSON should exist in failed_recordings
    preserved_wav = failed_dir / "test_recording.wav"
    error_json = failed_dir / "test_recording.error.json"
    
    assert preserved_wav.exists()
    assert error_json.exists()
    
    data = json.loads(error_json.read_text(encoding="utf-8"))
    assert "Simulated Ollama / Transcribe error" in data["error"]
    assert data["duration_seconds"] == 10.0
