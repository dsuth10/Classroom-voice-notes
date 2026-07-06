from pathlib import Path
from datetime import datetime
from app.audit.audit_logger import log_audit_event

class ObsidianWriter:
    def __init__(self, vault_path: str) -> None:
        self.vault_path = Path(vault_path)

    def write_note(
        self,
        classification_data: dict,
        transcript: str,
        duration_seconds: int,
        audio_file_path: str = "",
    ) -> str:
        """Writes a YAML-frontmatter enabled Markdown file into the Obsidian vault folder structure.
        
        Creates missing subfolders automatically. Returns the path of the created file.
        """
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Obsidian Vault directory does not exist: {self.vault_path}")
            
        category = classification_data.get("category", "general_note")
        route = classification_data.get("route", "local_obsidian")
        sensitivity = classification_data.get("sensitivity", "unknown")
        telegram_allowed = classification_data.get("telegram_allowed", False)
        confidence = classification_data.get("confidence", 0.0)
        title = classification_data.get("title", "Voice Note")
        
        # Determine the target subfolder inside the vault based on the category/route
        subfolder_map = {
            "student_note": "Student Notes",
            "behaviour_note": "Behaviour Notes",
            "maths_note": "Maths Notes",
            "english_note": "English Notes",
            "science_note": "Science Notes",
            "hass_note": "HASS Notes",
            "digitech_note": "Digital Technologies Notes",
            "designtech_note": "Design Technologies Notes",
            "reminder": "Reminders",
            "email_draft": "Email Drafts",
            "agent_task": "Agent Task Archive",
            "review_queue": "Review Queue",
            "general_note": "Inbox"
        }
        
        folder_name = subfolder_map.get(category, "Inbox")
        target_dir = self.vault_path / "Classroom Voice Notes" / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure Audio directory exists if audio path is given
        if audio_file_path:
            audio_dir = self.vault_path / "Classroom Voice Notes" / "Audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            relative_audio_path = f"../Audio/{Path(audio_file_path).name}"
        else:
            relative_audio_path = ""
            
        # Generate safe filename: YYYY-MM-DD_HH-MM-SS_category.md
        now = datetime.now()
        safe_title = title.lower().replace(" ", "_").replace(":", "-").replace("/", "-")
        # Keep filename under reasonable length
        if len(safe_title) > 50:
            safe_title = safe_title[:50]
        filename = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{safe_title}.md"
        file_path = target_dir / filename
        
        # Resolve student names to anonymised IDs
        category_fields = dict(classification_data.get("category_fields", {}))
        students_mentioned = category_fields.get("students_mentioned")
        if students_mentioned:
            from app.privacy.student_registry import StudentRegistry
            registry = StudentRegistry(str(self.vault_path))
            category_fields["students"] = registry.anonymise_list(students_mentioned)
        
        # Build Base Frontmatter
        base_frontmatter = {
            "type": "classroom-voice-note",
            "route": route,
            "sensitivity": sensitivity,
            "created": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "category": category,
            "status": "captured",
            "source": "local-voice-note-app",
            "duration_seconds": duration_seconds,
            "audio_file": relative_audio_path,
            "transcription_engine": "whisper.cpp",
            "telegram_allowed": telegram_allowed,
            "confidence": confidence,
            "tags": classification_data.get("tags", ["classroom-note", category.replace("_", "-")])
        }
        if classification_data.get("summary"):
            base_frontmatter["summary"] = classification_data["summary"]
            
        # Render using NoteTemplates
        from app.destinations.note_templates import NoteTemplates
        full_content = NoteTemplates.render(
            category=category,
            title=title,
            now_str=now.strftime('%d %B %Y, %I:%M %p'),
            transcript=transcript,
            base_frontmatter=base_frontmatter,
            category_fields=category_fields
        )
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            log_audit_event("OBSIDIAN_WRITE_SUCCESS", "session", f"Obsidian note saved: {file_path}")
            return str(file_path)
        except Exception as e:
            log_audit_event("OBSIDIAN_WRITE_ERROR", "session", f"Failed to write note: {e}")
            raise e
