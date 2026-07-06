import json
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List
from PySide6.QtCore import QObject, QTimer, Slot
from plyer import notification
from app.audit.audit_logger import log_audit_event

class ReminderEngine(QObject):
    def __init__(self, vault_path: str) -> None:
        super().__init__()
        self.vault_path = Path(vault_path)
        self.db_path = self.vault_path / "Classroom Voice Notes" / "reminders.json"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_reminders)
        
    def start(self, interval_ms: int = 30000) -> None:
        """Starts the periodic check timer (default: every 30 seconds)."""
        self.timer.start(interval_ms)
        log_audit_event("REMINDER_ENGINE_START", "session", f"Reminder engine started, polling every {interval_ms/1000}s")
        # Run an initial check immediately on startup
        self.check_reminders()

    def stop(self) -> None:
        self.timer.stop()
        log_audit_event("REMINDER_ENGINE_STOP", "session", "Reminder engine stopped")

    def _load_reminders(self) -> List[Dict[str, Any]]:
        if not self.db_path.exists():
            return []
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            log_audit_event("REMINDER_LOAD_ERROR", "session", f"Failed to load reminders: {e}")
        return []

    def _save_reminders(self, reminders: List[Dict[str, Any]]) -> None:
        try:
            # Ensure the directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(reminders, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log_audit_event("REMINDER_SAVE_ERROR", "session", f"Failed to save reminders: {e}")

    def add_reminder(self, title: str, summary: str, reminder_time_str: str, file_path: str) -> None:
        """Adds a new reminder to the JSON store."""
        reminders = self._load_reminders()
        
        # Avoid duplicate entries
        if any(r.get("file_path") == file_path for r in reminders):
            return

        reminder_id = f"rem-{int(datetime.now().timestamp())}"
        new_reminder = {
            "id": reminder_id,
            "title": title,
            "summary": summary,
            "reminder_time": reminder_time_str,
            "file_path": file_path,
            "status": "captured",
            "created_at": datetime.now().isoformat()
        }
        reminders.append(new_reminder)
        self._save_reminders(reminders)
        log_audit_event("REMINDER_ADDED", "session", f"Scheduled reminder '{title}' for {reminder_time_str}")

    @Slot()
    def check_reminders(self) -> None:
        """Checks for any pending reminders that are due and fires notifications."""
        reminders = self._load_reminders()
        if not reminders:
            return

        now = datetime.now()
        updated = False

        for r in reminders:
            if r.get("status") != "captured":
                continue

            reminder_time_str = r.get("reminder_time")
            if not reminder_time_str:
                continue

            try:
                # Standard YYYY-MM-DD HH:MM:SS format
                reminder_time = datetime.strptime(reminder_time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    # Fallback ISO format
                    reminder_time = datetime.fromisoformat(reminder_time_str)
                except ValueError:
                    # Invalid format: skip or mark as broken
                    r["status"] = "invalid_format"
                    updated = True
                    continue

            if now >= reminder_time:
                # Trigger Notification!
                title = r.get("title", "Voice Note Reminder")
                summary = r.get("summary", "A scheduled reminder is due.")
                file_path_str = r.get("file_path", "")

                log_audit_event("REMINDER_DUE", "session", f"Reminder due: {title}")
                self._fire_notification(title, summary)
                
                # Update statuses
                r["status"] = "actioned"
                r["actioned_at"] = now.isoformat()
                updated = True
                
                # Update Markdown file frontmatter if file_path is valid
                if file_path_str:
                    self._update_markdown_status(file_path_str, "actioned")

        if updated:
            self._save_reminders(reminders)

    def _fire_notification(self, title: str, message: str) -> None:
        """Triggers a native Windows Toast notification."""
        try:
            notification.notify(
                title=title,
                message=message,
                app_name="Classroom Voice Notes",
                timeout=15
            )
            log_audit_event("NOTIFICATION_FIRED", "session", f"Notification fired: {title}")
        except Exception as e:
            log_audit_event("NOTIFICATION_ERROR", "session", f"Failed to display notification: {e}")

    def _update_markdown_status(self, file_path_str: str, new_status: str) -> None:
        """Safely updates the status field in the frontmatter of a markdown file."""
        file_path = Path(file_path_str)
        if not file_path.exists():
            log_audit_event("MD_UPDATE_WARNING", "session", f"Markdown file not found for status update: {file_path}")
            return
            
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Simple multiline regex replacement for YAML frontmatter
            # Replaces 'status: captured' with 'status: actioned'
            # (or whatever new_status is)
            updated_content, count = re.subn(
                r"^status:\s*[a-zA-Z0-9_\-]+",
                f"status: {new_status}",
                content,
                flags=re.MULTILINE
            )
            
            if count > 0:
                file_path.write_text(updated_content, encoding="utf-8")
                log_audit_event("MD_UPDATE_SUCCESS", "session", f"Updated status to '{new_status}' in {file_path.name}")
            else:
                log_audit_event("MD_UPDATE_FAIL", "session", f"Could not find status field to update in {file_path.name}")
        except Exception as e:
            log_audit_event("MD_UPDATE_ERROR", "session", f"Failed to update Markdown status: {e}")
