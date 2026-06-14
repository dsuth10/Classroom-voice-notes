from pathlib import Path
from datetime import datetime
from app.audit.audit_logger import log_audit_event

class ObsidianWriter:
    def __init__(self, vault_path: str) -> None:
        self.vault_path = Path(vault_path)

    def write_note(
        self,
        title: str,
        transcript: str,
        category: str,
        route: str,
        sensitivity: str,
        duration_seconds: int,
        audio_file_path: str = "",
        telegram_allowed: bool = False,
        confidence: float = 1.0,
    ) -> str:
        """Writes a YAML-frontmatter enabled Markdown file into the Obsidian vault folder structure.
        
        Creates missing subfolders automatically. Returns the path of the created file.
        """
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Obsidian Vault directory does not exist: {self.vault_path}")
            
        # Determine the target subfolder inside the vault based on the category/route
        # Mapping to match Obsidian Vault Design guidelines
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
            # Copy audio file path references or relative path representation
            relative_audio_path = f"../Audio/{Path(audio_file_path).name}"
        else:
            relative_audio_path = ""
            
        # Generate safe filename: YYYY-MM-DD_HH-MM-SS_category.md
        now = datetime.now()
        safe_title = title.lower().replace(" ", "_").replace(":", "-").replace("/", "-")
        filename = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{safe_title}.md"
        file_path = target_dir / filename
        
        # Build Markdown content with Frontmatter
        # Note: Australian spelling used for metadata parameters (e.g. behaviour, organisation)
        frontmatter = {
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
            "tags": ["classroom-note", category.replace("_", "-")]
        }
        
        # Build YAML frontmatter block
        yaml_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                yaml_lines.append(f"{k}:")
                for item in v:
                    yaml_lines.append(f"  - {item}")
            elif isinstance(v, bool):
                yaml_lines.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                yaml_lines.append(f"{k}: {v}")
            else:
                yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")
        
        # Markdown body
        body = f"""
# {title} — {now.strftime('%d %B %Y, %I:%M %p')}

## Transcript

{transcript}

## Router Decision

- Route: {route}
- Sensitivity: {sensitivity}
- Category: {category}
- Telegram allowed: {str(telegram_allowed).lower()}
- Confidence: {confidence}

## Review Status

- [ ] Checked transcript
- [ ] Edited for accuracy
- [ ] Added context if needed
"""
        
        full_content = "\n".join(yaml_lines) + "\n" + body
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            log_audit_event("OBSIDIAN_WRITE_SUCCESS", "session", f"Obsidian note saved: {file_path}")
            return str(file_path)
        except Exception as e:
            log_audit_event("OBSIDIAN_WRITE_ERROR", "session", f"Failed to write note: {e}")
            raise e
