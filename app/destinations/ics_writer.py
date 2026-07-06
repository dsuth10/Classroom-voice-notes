from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict
from icalendar import Calendar, Event
from app.audit.audit_logger import log_audit_event

class ICSWriter:
    def __init__(self, vault_path: str) -> None:
        self.vault_path = Path(vault_path)

    def write_ics(self, classification_data: Dict[str, Any], transcript: str = "") -> str:
        """Generates an RFC 5545 .ics file for a reminder and saves it to the vault's Calendar directory.
        
        Returns the path of the created .ics file.
        """
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Obsidian Vault directory does not exist: {self.vault_path}")
            
        calendar_dir = self.vault_path / "Classroom Voice Notes" / "Calendar"
        calendar_dir.mkdir(parents=True, exist_ok=True)
        
        reminder_time_str = classification_data.get("reminder_time")
        if not reminder_time_str:
            # Fallback: schedule 1 hour from now
            start_time = datetime.now() + timedelta(hours=1)
        else:
            try:
                # Expect YYYY-MM-DD HH:MM:SS format
                start_time = datetime.strptime(reminder_time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    # Try fallback ISO format
                    start_time = datetime.fromisoformat(reminder_time_str)
                except ValueError:
                    start_time = datetime.now() + timedelta(hours=1)
                    
        end_time = start_time + timedelta(minutes=15) # Default duration of 15 minutes
        
        title = classification_data.get("title", "Voice Note Reminder")
        summary = classification_data.get("summary", "")
        
        # Build ical object
        cal = Calendar()
        cal.add('prodid', '-//Classroom Voice Notes Reminder Engine//EN')
        cal.add('version', '2.0')
        
        event = Event()
        event.add('summary', title)
        event.add('dtstart', start_time)
        event.add('dtend', end_time)
        
        description = f"Summary: {summary}\n\nTranscript: {transcript}" if transcript else summary
        event.add('description', description)
        
        # Unique UID using timestamp
        uid_str = f"cvn-{int(datetime.now().timestamp())}@classroomvoicenotes"
        event.add('uid', uid_str)
        event.add('dtstamp', datetime.now())
        
        cal.add_component(event)
        
        # Generate safe filename
        safe_title = title.lower().replace(" ", "_").replace(":", "-").replace("/", "-")
        if len(safe_title) > 50:
            safe_title = safe_title[:50]
        filename = f"{start_time.strftime('%Y-%m-%d_%H-%M-%S')}_{safe_title}.ics"
        file_path = calendar_dir / filename
        
        try:
            with open(file_path, "wb") as f:
                f.write(cal.to_ical())
            log_audit_event("ICS_WRITE_SUCCESS", "session", f"Calendar event saved: {file_path}")
            return str(file_path)
        except Exception as e:
            log_audit_event("ICS_WRITE_ERROR", "session", f"Failed to write .ics file: {e}")
            raise e
