import asyncio
import json
import os
import shutil
import re
from datetime import datetime, timezone


from pathlib import Path
from typing import Any
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
    reminder_captured = Signal(dict, str) # Emits classification_data and note_path

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
            
            # Clean transcript
            preambles = [r"hey joshua[,\.]?", r"joshua note[,\.]?", r"hey jarvis[,\.]?", r"joshua[,\.]?"]
            for preamble in preambles:
                transcript = re.sub(f"^{preamble}\\s*", "", transcript, flags=re.IGNORECASE)
            
            commands = [r"save$", r"saved$", r"cancel$", r"stop$", r"discard$"]
            for cmd in commands:
                transcript = re.sub(f"\\s*{cmd}[\\.\\!\\?]*$", "", transcript, flags=re.IGNORECASE)
            
            transcript = transcript.strip()
            if transcript:
                transcript = transcript[0].upper() + transcript[1:]
                
            # 2. Classify transcript locally using Ollama
            self.state_changed.emit("CLASSIFYING")
            ollama_url = self.settings_manager.get("ollama_url")
            fast_model = self.settings_manager.get("fast_model", "qwen3.5:latest")
            classifier = OllamaClassifier(ollama_url, fast_model)
            
            recorded_at = datetime.now().isoformat()
            classification = classifier.classify(transcript, recorded_at, self.duration_seconds)
            
            confidence = classification.get("confidence", 0.5)
            sensitivity = classification.get("sensitivity", "unknown")
            
            # Two-pass classification if low confidence or unknown sensitivity
            if confidence < 0.75 or sensitivity == "unknown":
                log_audit_event("CLASSIFICATION_RETRY", "session", "Low confidence or unknown sensitivity. Using careful model.")
                careful_model = self.settings_manager.get("careful_model", "phi4:14b")
                careful_classifier = OllamaClassifier(ollama_url, careful_model)
                classification = careful_classifier.classify(transcript, recorded_at, self.duration_seconds)
                sensitivity = classification.get("sensitivity", "unknown")
            
            category = classification.get("category", "general_note")
            
            # 3. Check privacy safety rules using the Policy Gate
            self.state_changed.emit("POLICY_CHECKING")
            gate = PolicyGate()
            telegram_allowed = gate.is_telegram_allowed(sensitivity, category, transcript)
            classification["telegram_allowed"] = telegram_allowed
            
            if telegram_allowed:
                classification["route"] = "telegram_agent_task"
            else:
                classification["route"] = f"local_{category}"
            
            # 4. Route and write the Markdown note into the Obsidian vault
            self.state_changed.emit("ROUTING")
            vault_path = self.settings_manager.get("obsidian_vault_path")
            writer = ObsidianWriter(vault_path)
            
            self.state_changed.emit("WRITING_OUTPUT")
            
            note_path = writer.write_note(
                classification_data=classification,
                transcript=transcript,
                duration_seconds=self.duration_seconds,
                audio_file_path=self.wav_path
            )
            
            # If reminder, generate ICS and emit signal to register reminder on main thread
            if category == "reminder":
                from app.destinations.ics_writer import ICSWriter
                try:
                    ics_writer = ICSWriter(vault_path)
                    ics_writer.write_ics(classification, transcript)
                except Exception as e:
                    log_audit_event("ICS_WRITE_ERROR", "session", f"Failed to generate ICS: {e}")
                self.reminder_captured.emit(classification, note_path)
            
            # 5a. External route trigger if approved by Policy Gate and enabled
            # Bypassed if the new Supabase broker is active to prevent double-sending
            if (telegram_allowed 
                and self.settings_manager.get("agents.enabled")
                and not self.settings_manager.external_sharing_enabled()):
                from app.destinations.telegram_dispatcher import TelegramDispatcher
                dispatcher = TelegramDispatcher(self.settings_manager)
                dispatcher.dispatch(transcript, classification, note_path)
            
            # 5b. Central outbound routing service (handles off, safe_auto, review_all, trusted_auto)
            from app.destinations.outbound_routing_service import OutboundRoutingService

            routing_service = OutboundRoutingService(self.settings_manager)
            routing_service.handle_capture(
                classification=classification,
                transcript=transcript,
                note_path=note_path,
                recorded_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=self.duration_seconds,
            )
            
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
            # Preserve failed recording audio in recovery directory rather than deleting
            if os.path.exists(self.wav_path):
                try:
                    from app.utils.paths import get_failed_audio_dir
                    failed_dir = get_failed_audio_dir()
                    failed_dir.mkdir(parents=True, exist_ok=True)
                    dest_path = failed_dir / Path(self.wav_path).name
                    shutil.move(self.wav_path, dest_path)

                    
                    # Write diagnostic metadata sidecar
                    meta_path = failed_dir / f"{Path(self.wav_path).stem}.error.json"
                    meta_data = {
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "duration_seconds": self.duration_seconds,
                        "original_path": self.wav_path,
                        "error": str(e),
                    }
                    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")
                    log_audit_event("AUDIO_PRESERVED_ON_FAILURE", "session", f"Preserved failed recording to {dest_path}")
                except Exception as preservation_err:
                    log_audit_event("AUDIO_PRESERVATION_ERROR", "session", f"Failed to preserve WAV: {preservation_err}")
            log_audit_event("PIPELINE_ERROR", "session", f"Pipeline execution failed: {e}")
            self.error_occurred.emit(str(e))

