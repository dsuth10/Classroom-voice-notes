import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from icalendar import Calendar
from app.destinations.ics_writer import ICSWriter
from app.destinations.reminder_engine import ReminderEngine

def test_ics_writer_creates_file(tmp_path: Path) -> None:
    """Verifies that ICSWriter creates valid .ics files in the vault."""
    # Setup folders
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    
    writer = ICSWriter(str(vault_dir))
    
    # Classification data
    data = {
        "title": "Test Yard Duty",
        "summary": "Alex needs pickup",
        "reminder_time": "2026-07-06 17:30:00"
    }
    
    file_path_str = writer.write_ics(data, transcript="This is the raw text.")
    file_path = Path(file_path_str)
    
    assert file_path.exists()
    assert file_path.suffix == ".ics"
    
    # Check directory structure
    expected_dir = vault_dir / "Classroom Voice Notes" / "Calendar"
    assert expected_dir.exists()
    assert file_path.parent == expected_dir
    
    # Read and inspect content using icalendar parser
    content = file_path.read_bytes()
    cal = Calendar.from_ical(content)
    event = cal.walk('vevent')[0]
    
    assert event.get('summary') == "Test Yard Duty"
    assert event.get('description') == "Summary: Alex needs pickup\n\nTranscript: This is the raw text."
    
    # Check times (dates are returned as vDDDTypes/datetime objects)
    assert event.get('dtstart').dt == datetime(2026, 7, 6, 17, 30, 0)
    assert event.get('dtend').dt == datetime(2026, 7, 6, 17, 45, 0)


@patch("app.destinations.reminder_engine.notification")
def test_reminder_engine_lifecycle(mock_notify: MagicMock, tmp_path: Path) -> None:
    """Tests the full lifecycle of adding, saving, loading and triggering reminders."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    
    # Make sure Classroom Voice Notes dir exists
    (vault_dir / "Classroom Voice Notes").mkdir()
    
    # Create engine
    engine = ReminderEngine(str(vault_dir))
    
    # Verify initial state
    assert len(engine._load_reminders()) == 0
    
    # Create a dummy note file to simulate updating its status
    note_file = vault_dir / "Classroom Voice Notes" / "Reminders" / "test_note.md"
    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text("---\nstatus: captured\n---\nBody content", encoding="utf-8")
    
    # 1. Add a reminder due in the past (to trigger immediately)
    past_time = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    engine.add_reminder(
        title="Due Reminder",
        summary="This reminder is in the past",
        reminder_time_str=past_time,
        file_path=str(note_file)
    )
    
    # 2. Add a reminder in the future (should not trigger)
    future_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    engine.add_reminder(
        title="Future Reminder",
        summary="This reminder is in the future",
        reminder_time_str=future_time,
        file_path=""
    )
    
    # Verify both exist
    reminders = engine._load_reminders()
    assert len(reminders) == 2
    assert reminders[0]["status"] == "captured"
    assert reminders[1]["status"] == "captured"
    
    # Run verification check
    engine.check_reminders()
    
    # Check that notification was triggered only once
    mock_notify.notify.assert_called_once()
    args, kwargs = mock_notify.notify.call_args
    assert kwargs["title"] == "Due Reminder"
    assert kwargs["message"] == "This reminder is in the past"
    
    # Check updated statuses
    updated_reminders = engine._load_reminders()
    assert updated_reminders[0]["status"] == "actioned"
    assert updated_reminders[1]["status"] == "captured"
    
    # Verify markdown file status was updated to actioned
    note_content = note_file.read_text(encoding="utf-8")
    assert "status: actioned" in note_content
    assert "status: captured" not in note_content
