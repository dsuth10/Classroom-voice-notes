from pathlib import Path
from unittest import mock
import pytest
from app.transcription.transcriber import WhisperTranscriber

@pytest.mark.asyncio
async def test_transcriber_calls_subprocess(tmp_path: Path) -> None:
    """Verifies that the transcriber runs whisper.exe via async subprocess."""
    audio_file = tmp_path / "note.wav"
    audio_file.touch()
    
    # We mock the whisper executable to avoid needing the real binary in tests
    bin_path = tmp_path / "whisper.exe"
    bin_path.touch()
    model_path = tmp_path / "model.bin"
    model_path.touch()
    
    transcriber = WhisperTranscriber(str(bin_path), str(model_path))
    
    # Mock asyncio subprocess creation
    mock_process = mock.AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"", b"")
    
    # whisper.cpp output is written to a .txt file (e.g. note.wav.txt)
    txt_output = tmp_path / "note.wav.txt"
    txt_output.write_text("Hello this is a test note.", encoding="utf-8")
    
    with mock.patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await transcriber.transcribe(str(audio_file))
        
        mock_exec.assert_called_once()
        assert result == "Hello this is a test note."
        
        # Verify temporary txt file was cleaned up
        assert not txt_output.exists()
