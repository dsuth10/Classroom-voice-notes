import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict
from PySide6.QtCore import QThread, Signal
from app.transcription.transcriber import WhisperTranscriber
from app.ollama_router.classifier import OllamaClassifier
from app.ollama_router.policy_gate import PolicyGate
from app.destinations.obsidian_writer import ObsidianWriter
from app.audit.audit_logger import log_audit_event

class PipelineWorker(QThread):
    """Background worker thread to execute the transcription, classification, and routing pipeline."""
    state_changed = Signal(str)      # Emits current stage: "CLASSIFYING", "POLICY_CHECKING", "ROUTING", "WRITING_OUTPUT"
    finished_pipeline = Signal(str)  # Emits the path of the saved Obsidian markdown note
    error_occurred = Signal(str)     # Emits error description if any step fails

    def __init__(
        self,
        wav_path: str,
        settings_manager: Any,
        duration_seconds: float
    ) -> None:
        super().__init__()
        self.wav_path = wav_path
        self.settings_manager = settings_manager
        self.duration_seconds = int(duration_seconds)

    def run(self) -> None:
        try:
            # 1. Transcribe audio file using Whisper
            # Since WhisperTranscriber.transcribe is asynchronous, we run it using asyncio.run in this thread
            self.state_changed.emit("TRANSCRIBING")
            bin_path = self.settings_manager.get("whisper_bin_path")
            model_path = self.settings_manager.get("whisper_model_path")
            
            transcriber = WhisperTranscriber(bin_path, model_path)
            transcript = asyncio.run(transcriber.transcribe(self.wav_path))
            
            if not transcript:
                transcript = "[Empty recording]"
                
            # 2. Classify transcript locally using Ollama
            self.state_changed.emit("CLASSIFYING")
            ollama_url = self.settings_manager.get("ollama_url")
            fast_model = self.settings_manager.get("fast_model")
            classifier = OllamaClassifier(ollama_url, fast_model)
            classification = classifier.classify(transcript)
            
            category = classification.get("category", "general_note")
            sensitivity = classification.get("sensitivity", "teacher_private")
            confidence = classification.get("confidence", 0.5)
            
            # 3. Check privacy safety rules using the Policy Gate
            self.state_changed.emit("POLICY_CHECKING")
            gate = PolicyGate()
            telegram_allowed = gate.is_telegram_allowed(sensitivity, category, transcript)
            
            # 4. Route and write the Markdown note into the Obsidian vault
            self.state_changed.emit("ROUTING")
            vault_path = self.settings_manager.get("obsidian_vault_path")
            writer = ObsidianWriter(vault_path)
            
            # Formulate note title from the first few words of the transcript
            words = transcript.strip().split()
            title = " ".join(words[:5]) if words else "Voice Note"
            title = "".join(c for c in title if c.isalnum() or c.isspace())
            if not title.strip():
                title = "Voice Note"
                
            self.state_changed.emit("WRITING_OUTPUT")
            
            if telegram_allowed:
                route = "telegram_agent_task"
            else:
                route = f"local_{category}"
                
            note_path = writer.write_note(
                title=title,
                transcript=transcript,
                category=category,
                route=route,
                sensitivity=sensitivity,
                duration_seconds=self.duration_seconds,
                audio_file_path=self.wav_path,
                telegram_allowed=telegram_allowed,
                confidence=confidence
            )
            
            # 5. External route trigger if approved by Policy Gate and enabled
            if telegram_allowed and self.settings_manager.get("telegram_enabled"):
                token = self.settings_manager.get("telegram_token")
                chat_id = self.settings_manager.get("telegram_chat_id")
                if token and chat_id:
                    try:
                        import httpx
                        # Send text message to Telegram channel/chat
                        url = f"https://api.telegram.org/bot{token}/sendMessage"
                        payload = {"chat_id": chat_id, "text": f"New Agent Task:\n{transcript}"}
                        httpx.post(url, json=payload, timeout=10.0)
                        log_audit_event("TELEGRAM_SEND_SUCCESS", "session", f"Task sent to Telegram chat {chat_id}")
                    except Exception as e:
                        log_audit_event("TELEGRAM_SEND_ERROR", "session", f"Failed to send task to Telegram: {e}")
            
            # 6. Copy WAV file to Obsidian Vault Audio directory and clean up temporary audio file
            if note_path and os.path.exists(self.wav_path):
                dest_audio_dir = Path(vault_path) / "Classroom Voice Notes" / "Audio"
                dest_audio_dir.mkdir(parents=True, exist_ok=True)
                dest_audio_path = dest_audio_dir / Path(self.wav_path).name
                
                # Copy audio to vault and remove local temp cache
                shutil.copy2(self.wav_path, dest_audio_path)
                os.remove(self.wav_path)
                log_audit_event("AUDIO_MOVE_SUCCESS", "session", f"Audio moved to vault at {dest_audio_path}")
                
            self.finished_pipeline.emit(note_path)
            
        except Exception as e:
            # Clean up temporary audio file if failure occurs to avoid orphaned files on disk
            if os.path.exists(self.wav_path):
                try:
                    os.remove(self.wav_path)
                except Exception:
                    pass
            log_audit_event("PIPELINE_ERROR", "session", f"Pipeline execution failed: {e}")
            self.error_occurred.emit(str(e))
