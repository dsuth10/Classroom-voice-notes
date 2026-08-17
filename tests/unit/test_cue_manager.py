"""Unit tests for AudioCueManager and WAV synthesis."""

import io
import wave
from unittest.mock import MagicMock, patch
import pytest

from app.audio.cue_manager import AudioCueManager, synthesize_tone
from app.config.settings import SettingsManager


def test_synthesize_tone_produces_valid_wav() -> None:
    """Verifies that synthesize_tone generates valid 16-bit PCM WAV bytes."""
    wav_bytes = synthesize_tone([440.0, 880.0], [50, 50], volume=0.5, sample_rate=22050)
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes

    # Parse with standard wave module
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 22050
        n_frames = wf.getnframes()
        # 100ms at 22050Hz = ~2205 frames
        assert 2200 <= n_frames <= 2210


def test_synthesize_tone_volume_scaling() -> None:
    """Verifies volume scaling behaves gracefully at boundaries."""
    zero_bytes = synthesize_tone([440.0], [50], volume=0.0)
    assert len(zero_bytes) > 44  # Valid WAV header + frames

    full_bytes = synthesize_tone([440.0], [50], volume=1.0)
    assert len(full_bytes) == len(zero_bytes)


def test_cue_manager_initialisation() -> None:
    """Verifies all 4 required sound cues are pre-built on init."""
    cue_manager = AudioCueManager()
    assert "start" in cue_manager._cues
    assert "saved" in cue_manager._cues
    assert "cancelled" in cue_manager._cues
    assert "error" in cue_manager._cues

    for name, data in cue_manager._cues.items():
        assert isinstance(data, bytes)
        assert data.startswith(b"RIFF"), f"Cue '{name}' is not a valid RIFF WAV"


def test_cue_manager_settings_integration(tmp_path: pytest.TempPathFactory) -> None:
    """Verifies cue manager respects settings for volume and enable/disable."""
    settings = SettingsManager()
    settings.set("audio.earcons_enabled", False)
    settings.set("audio.earcons_volume", 0.3)

    cue_manager = AudioCueManager(settings)
    assert cue_manager.is_enabled() is False
    assert cue_manager.get_volume() == 0.3

    # When disabled, play() should immediately return False without calling winsound
    with patch("winsound.PlaySound", create=True) as mock_play:
        result = cue_manager.play("start")
        assert result is False
        mock_play.assert_not_called()


def test_cue_manager_play_success() -> None:
    """Verifies play dispatches the correct WAV buffer to winsound."""
    settings = SettingsManager()
    settings.set("audio.earcons_enabled", True)
    cue_manager = AudioCueManager(settings)

    with patch("winsound.PlaySound", create=True) as mock_play:
        result = cue_manager.play("saved")
        assert result is True
        mock_play.assert_called_once()
        args, _ = mock_play.call_args
        assert args[0] == cue_manager._cues["saved"]


def test_cue_manager_unknown_cue() -> None:
    """Verifies playing an unknown cue returns False safely."""
    cue_manager = AudioCueManager()
    result = cue_manager.play("non_existent_cue_name")
    assert result is False
