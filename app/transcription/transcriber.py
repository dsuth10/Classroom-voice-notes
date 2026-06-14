import asyncio
import os
from pathlib import Path
from app.audit.audit_logger import log_audit_event

class WhisperTranscriber:
    def __init__(self, bin_path: str, model_path: str) -> None:
        self.bin_path = bin_path
        self.model_path = model_path

    async def transcribe(self, wav_path: str) -> str:
        """Runs whisper.cpp on the given WAV file and returns the transcribed text."""
        log_audit_event("TRANSCRIPTION_START", "session", f"Transcribing WAV file: {wav_path}")
        
        if not Path(self.bin_path).exists():
            raise FileNotFoundError(f"whisper.cpp binary not found at: {self.bin_path}")
        if not Path(self.model_path).exists():
            raise FileNotFoundError(f"whisper.cpp model not found at: {self.model_path}")
            
        # whisper.cpp by default creates an output text file named <wav_path>.txt when using -otxt
        # Command format: whisper.exe -m <model> -f <wav> -otxt
        # Note: we pass the parameters directly as a list
        process = await asyncio.create_subprocess_exec(
            self.bin_path,
            "-m", self.model_path,
            "-f", wav_path,
            "-otxt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            err_msg = stderr.decode(errors="ignore")
            log_audit_event("TRANSCRIPTION_ERROR", "session", f"whisper.cpp exited with code {process.returncode}: {err_msg}")
            raise RuntimeError(f"whisper.cpp failed: {err_msg}")
            
        # Read the generated text file
        txt_path = Path(f"{wav_path}.txt")
        if not txt_path.exists():
            raise FileNotFoundError(f"Expected transcription text output not found at: {txt_path}")
            
        try:
            transcript = txt_path.read_text(encoding="utf-8").strip()
            log_audit_event("TRANSCRIPTION_SUCCESS", "session", f"Transcript parsed: {transcript}")
            return transcript
        finally:
            # Clean up the temporary txt file
            if txt_path.exists():
                os.remove(txt_path)
