"""Audio Cue Manager — Zero-latency harmonic earcons for hands-free state transitions."""

import io
import math
import struct
import wave
from typing import Any, Dict, Optional
from app.audit.audit_logger import log_audit_event


def synthesize_tone(
    frequencies: list[float],
    durations_ms: list[int],
    volume: float = 0.7,
    sample_rate: int = 22050,
) -> bytes:
    """Procedurally synthesizes a multi-frequency harmonic WAV buffer in memory.

    Applies smooth cosine attack/decay envelopes to prevent clicks or popping.
    """
    raw_samples = []

    clamped_volume = max(0.0, min(1.0, volume))
    max_amp = 32767 * clamped_volume

    for freq, duration in zip(frequencies, durations_ms):
        num_samples = int(sample_rate * (duration / 1000.0))
        fade_samples = max(1, int(sample_rate * 0.015))  # 15ms fade envelope

        for i in range(num_samples):
            # Calculate cosine envelope to prevent acoustic clicks
            envelope = 1.0
            if i < fade_samples:
                envelope = 0.5 * (1.0 - math.cos(math.pi * i / fade_samples))
            elif i > num_samples - fade_samples:
                remaining = num_samples - i
                envelope = 0.5 * (1.0 - math.cos(math.pi * remaining / fade_samples))

            val = int(max_amp * envelope * math.sin(2.0 * math.pi * freq * i / sample_rate))
            val = max(-32768, min(32767, val))
            raw_samples.append(val)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(sample_rate)
        packed_data = struct.pack(f"<{len(raw_samples)}h", *raw_samples)
        wav_file.writeframes(packed_data)

    return buffer.getvalue()


class AudioCueManager:
    """Manages generation and playback of non-intrusive sound cues."""

    def __init__(self, settings_manager: Optional[Any] = None) -> None:
        self.settings_manager = settings_manager
        self._cues: Dict[str, bytes] = {}
        self.build_cues()

    def get_volume(self) -> float:
        if self.settings_manager:
            val = self.settings_manager.get("audio.earcons_volume")
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return 0.7

    def is_enabled(self) -> bool:
        if self.settings_manager:
            val = self.settings_manager.get("audio.earcons_enabled")
            if val is not None:
                return bool(val)
        return True

    def build_cues(self) -> None:
        """Synthesizes the 4 distinct earcons with the configured volume."""
        vol = self.get_volume()

        # 1. Start recording cue: Crisp ascending double-tone (C5 523Hz -> E5 659Hz)
        self._cues["start"] = synthesize_tone([523.25, 659.25], [70, 70], volume=vol)

        # 2. Note saved cue: Pleasant major triad arpeggio (C5 523Hz -> E5 659Hz -> G5 784Hz)
        self._cues["saved"] = synthesize_tone([523.25, 659.25, 783.99], [80, 80, 110], volume=vol)

        # 3. Cancelled / Discarded cue: Muted descending tone (A4 440Hz -> C4 261Hz)
        self._cues["cancelled"] = synthesize_tone([440.0, 261.63], [90, 120], volume=vol * 0.8)

        # 4. Error cue: Subtle low double-tone (A3 220Hz -> G3 196Hz)
        self._cues["error"] = synthesize_tone([220.0, 196.0], [90, 110], volume=vol * 0.9)

    def play(self, cue_name: str) -> bool:
        """Plays the named sound cue asynchronously without blocking the UI or audio capture."""
        if not self.is_enabled():
            return False

        wav_bytes = self._cues.get(cue_name)
        if not wav_bytes:
            log_audit_event("AUDIO_CUE_UNKNOWN", "cue_manager", f"Unknown audio cue '{cue_name}' requested")
            return False

        try:
            import winsound

            # SND_MEMORY: wav bytes in memory
            # SND_ASYNC: non-blocking playback
            # SND_NODEFAULT: do not play system default beep if error
            winsound.PlaySound(
                wav_bytes,
                winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            log_audit_event("AUDIO_CUE_PLAYED", "cue_manager", f"Played audio cue '{cue_name}'")
            return True
        except ImportError:
            # Non-Windows platform fallback (e.g. CI / Linux test environment)
            return True
        except Exception as e:
            log_audit_event("AUDIO_CUE_ERROR", "cue_manager", f"Failed to play cue '{cue_name}': {e}")
            return False
