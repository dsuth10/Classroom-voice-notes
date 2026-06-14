from pathlib import Path
from unittest import mock
import pytest
from app.utils.downloader import download_whisper_model

def test_download_whisper_model_skips_if_exists(tmp_path: Path) -> None:
    """Verifies that the downloader does nothing if the model file already exists."""
    dest = tmp_path / "ggml-base.en.bin"
    dest.touch()
    
    with mock.patch("urllib.request.urlopen") as mock_urlopen:
        download_whisper_model(dest)
        mock_urlopen.assert_not_called()

def test_download_whisper_model_downloads_successfully(tmp_path: Path) -> None:
    """Verifies that the downloader successfully writes model content retrieved via urlopen."""
    dest = tmp_path / "ggml-base.en.bin"
    
    mock_response = mock.MagicMock()
    mock_response.info.return_value = {"Content-Length": "10"}
    mock_response.read.side_effect = [b"model_data", b""]
    
    mock_context = mock.MagicMock()
    mock_context.__enter__.return_value = mock_response
    
    with mock.patch("urllib.request.urlopen", return_value=mock_context) as mock_urlopen_func:
        download_whisper_model(dest)
        mock_urlopen_func.assert_called_once()
        
    assert dest.exists()
    assert dest.read_bytes() == b"model_data"
