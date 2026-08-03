import os
import threading
from pathlib import Path
from typing import Any, Dict, Tuple
from PySide6.QtCore import QObject, QTimer, Slot
from app.audit.audit_logger import log_audit_event
from app.ollama_router.classifier import OllamaClassifier
from app.destinations.obsidian_writer import ObsidianWriter

class ReviewManager(QObject):
    def __init__(self, vault_path: str, settings_manager: Any, reminder_engine: Any = None) -> None:
        super().__init__()
        self.vault_path = Path(vault_path)
        self.settings_manager = settings_manager
        self.reminder_engine = reminder_engine
        
        self.queue_dir = self.vault_path / "Classroom Voice Notes" / "Review Queue"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan_queue)
        
    def start(self, interval_ms: int = 60000) -> None:
        """Starts periodic scanning of the Review Queue (default: every 60 seconds)."""
        self.timer.start(interval_ms)
        log_audit_event("REVIEW_MANAGER_START", "session", f"Review manager started, scanning every {interval_ms/1000}s")
        # Run the initial scan in a background thread to avoid blocking the UI on startup
        threading.Thread(target=self.scan_queue, daemon=True).start()

    def stop(self) -> None:
        self.timer.stop()
        log_audit_event("REVIEW_MANAGER_STOP", "session", "Review manager stopped")

    def _parse_note(self, file_path: Path) -> Tuple[Dict[str, Any], str, bool]:
        """Parses frontmatter, transcript, and checks if checkboxes are complete."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            log_audit_event("REVIEW_PARSE_ERROR", "session", f"Failed to read note {file_path.name}: {e}")
            return {}, "", False

        # Parse frontmatter
        frontmatter = {}
        if content.startswith("---"):
            parts = content.split("---")
            if len(parts) >= 3:
                yaml_str = parts[1]
                current_key = None
                for line in yaml_str.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("-") and current_key:
                        if not isinstance(frontmatter.get(current_key), list):
                            frontmatter[current_key] = []
                        frontmatter[current_key].append(line[1:].strip())
                    elif ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        if val == "":
                            frontmatter[key] = []
                            current_key = key
                        else:
                            if val.lower() == "true":
                                frontmatter[key] = True
                            elif val.lower() == "false":
                                frontmatter[key] = False
                            else:
                                try:
                                    if "." in val:
                                        frontmatter[key] = float(val)
                                    else:
                                        frontmatter[key] = int(val)
                                except ValueError:
                                    frontmatter[key] = val
                            current_key = None

        # Parse transcript
        transcript = ""
        trans_header = "## Transcript"
        idx = content.find(trans_header)
        if idx != -1:
            body = content[idx + len(trans_header):]
            next_header_idx = body.find("##")
            if next_header_idx != -1:
                body = body[:next_header_idx]
            transcript = body.strip()

        # Check if fully reviewed (has checkboxes and all are checked)
        has_checked = "- [x]" in content.lower()
        has_unchecked = "- [ ]" in content
        is_reviewed = has_checked and not has_unchecked

        return frontmatter, transcript, is_reviewed

    def _route_processed_note(self, classification: Dict[str, Any], transcript: str, original_file: Path, frontmatter: Dict[str, Any]) -> None:
        """Routes a processed note to its final destination and deletes the review queue file."""
        writer = ObsidianWriter(str(self.vault_path))
        
        # Resolve audio path from frontmatter
        audio_rel_path = frontmatter.get("audio_file", "")
        audio_abs_path = ""
        if audio_rel_path:
            # e.g., "../Audio/note_123.wav" -> vault_path / "Classroom Voice Notes" / "Audio" / "note_123.wav"
            audio_filename = Path(audio_rel_path).name
            audio_abs_path = str(self.vault_path / "Classroom Voice Notes" / "Audio" / audio_filename)

        duration = frontmatter.get("duration_seconds", 0)

        # Write new note
        try:
            note_path = writer.write_note(
                classification_data=classification,
                transcript=transcript,
                duration_seconds=duration,
                audio_file_path=audio_abs_path
            )
            log_audit_event("REVIEW_ROUTED", "session", f"Note routed from Review Queue to final location: {note_path}")
            
            # Delete old review note
            os.remove(original_file)
            log_audit_event("REVIEW_CLEANED", "session", f"Deleted queue file: {original_file.name}")

            # If reminder, schedule it
            category = classification.get("category")
            reminder_time = classification.get("reminder_time")
            if category == "reminder" and reminder_time and self.reminder_engine:
                self.reminder_engine.add_reminder(
                    title=classification.get("title", "Voice Note Reminder"),
                    summary=classification.get("summary", ""),
                    reminder_time_str=reminder_time,
                    file_path=note_path
                )
        except Exception as e:
            log_audit_event("REVIEW_ROUTE_ERROR", "session", f"Failed to route note {original_file.name}: {e}")

    @Slot()
    def scan_queue(self) -> None:
        """Scans the Review Queue folder and processes eligible notes."""
        if not self.queue_dir.exists():
            return

        notes = list(self.queue_dir.glob("*.md"))
        if not notes:
            return

        log_audit_event("REVIEW_SCAN_START", "session", f"Scanning Review Queue: found {len(notes)} files")

        ollama_url = self.settings_manager.get("ollama_url")
        careful_model = self.settings_manager.get("careful_model", "phi4:14b")

        for note_file in notes:
            frontmatter, transcript, is_reviewed = self._parse_note(note_file)
            if not frontmatter or not transcript:
                continue

            confidence = frontmatter.get("confidence", 0.5)
            category = frontmatter.get("category", "")
            
            # Scenario 1: Auto-Reclassify if confidence is 0.0 (previous failure)
            if confidence == 0.0 or category == "review_queue":
                log_audit_event("REVIEW_AUTO_RECLASSIFY", "session", f"Attempting auto-reclassification for {note_file.name}")
                classifier = OllamaClassifier(ollama_url, careful_model)
                
                # Check if Ollama is online by running classification
                classification = classifier.classify(transcript, frontmatter.get("created", ""), frontmatter.get("duration_seconds", 0))
                new_confidence = classification.get("confidence", 0.0)
                new_category = classification.get("category", "")

                if new_confidence >= 0.75 and new_category != "review_queue":
                    log_audit_event("REVIEW_AUTO_SUCCESS", "session", f"Auto-reclassification successful for {note_file.name} (confidence={new_confidence})")
                    self._route_processed_note(classification, transcript, note_file, frontmatter)
                    continue

            # Scenario 2: User manually checked all review checkboxes
            if is_reviewed:
                log_audit_event("REVIEW_MANUAL_COMPLETE", "session", f"User completed manual review for {note_file.name}")
                classifier = OllamaClassifier(ollama_url, careful_model)
                classification = classifier.classify(transcript, frontmatter.get("created", ""), frontmatter.get("duration_seconds", 0))
                
                # Manual review overrides confidence thresholds, we route whatever the classifier suggests
                self._route_processed_note(classification, transcript, note_file, frontmatter)
