import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.destinations.review_manager import ReviewManager

def test_review_manager_note_parsing(tmp_path: Path) -> None:
    """Verifies that ReviewManager correctly parses frontmatter, transcripts, and checkbox states."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    
    manager = ReviewManager(str(vault_dir), settings_manager=MagicMock())
    
    # 1. Unchecked boxes note
    note_content_1 = """---
type: classroom-voice-note
confidence: 0.0
category: review_queue
created: 2026-07-06 12:00:00
duration_seconds: 10
audio_file: ../Audio/note_123.wav
tags:
  - classroom-note
  - review-queue
---
# Note Title — 06 July 2026

## Transcript

Please remind me to print worksheets.

## Router Decision
- Category: review_queue

## Review Status
- [ ] Checked transcript
- [x] Edited for accuracy
- [ ] Added context if needed
"""
    note_file_1 = vault_dir / "note_1.md"
    note_file_1.write_text(note_content_1, encoding="utf-8")
    
    frontmatter, transcript, is_reviewed = manager._parse_note(note_file_1)
    
    assert frontmatter["confidence"] == 0.0
    assert frontmatter["category"] == "review_queue"
    assert frontmatter["duration_seconds"] == 10
    assert frontmatter["tags"] == ["classroom-note", "review-queue"]
    assert transcript == "Please remind me to print worksheets."
    assert is_reviewed is False

    # 2. Fully checked boxes note
    note_content_2 = """---
type: classroom-voice-note
confidence: 0.5
category: review_queue
created: 2026-07-06 12:00:00
duration_seconds: 15
---
# Note Title

## Transcript

Help Alex with reading.

## Review Status
- [x] Checked transcript
- [X] Edited for accuracy
- [x] Added context if needed
"""
    note_file_2 = vault_dir / "note_2.md"
    note_file_2.write_text(note_content_2, encoding="utf-8")
    
    _, transcript_2, is_reviewed_2 = manager._parse_note(note_file_2)
    assert transcript_2 == "Help Alex with reading."
    assert is_reviewed_2 is True


@patch("app.destinations.review_manager.OllamaClassifier")
@patch("app.destinations.review_manager.ObsidianWriter")
def test_review_manager_auto_reclassification(mock_writer_cls: MagicMock, mock_classifier_cls: MagicMock, tmp_path: Path) -> None:
    """Verifies auto-reclassification and routing of 0.0 confidence notes."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    
    queue_dir = vault_dir / "Classroom Voice Notes" / "Review Queue"
    queue_dir.mkdir(parents=True)
    
    # Mock settings manager
    settings = MagicMock()
    settings.get.side_effect = lambda k, default=None: {
        "ollama_url": "http://localhost:11434",
        "careful_model": "phi4:14b"
    }.get(k, default)
    
    # Mock reminder engine
    mock_reminders = MagicMock()
    
    manager = ReviewManager(str(vault_dir), settings, mock_reminders)
    
    # Setup mock classifier output
    mock_classifier = MagicMock()
    mock_classifier.classify.return_value = {
        "category": "reminder",
        "route": "local_reminder",
        "sensitivity": "non_sensitive",
        "title": "Print Assessment",
        "summary": "Need to print assessment",
        "reminder_time": "2026-07-06 13:00:00",
        "confidence": 0.95
    }
    mock_classifier_cls.return_value = mock_classifier
    
    # Setup mock writer output
    mock_writer = MagicMock()
    mock_writer.write_note.return_value = str(vault_dir / "Classroom Voice Notes" / "Reminders" / "note_routed.md")
    mock_writer_cls.return_value = mock_writer
    
    # Place a 0.0 confidence note in Review Queue
    note_content = """---
type: classroom-voice-note
confidence: 0.0
category: review_queue
created: 2026-07-06 12:00:00
duration_seconds: 10
audio_file: ../Audio/note_123.wav
---
# Title
## Transcript
Remind me to print worksheets tomorrow at 1pm.
## Review Status
- [ ] Checked transcript
"""
    note_file = queue_dir / "note_to_auto_reclassify.md"
    note_file.write_text(note_content, encoding="utf-8")
    
    # Run scan
    manager.scan_queue()
    
    # Verify classification and writer calls
    mock_classifier.classify.assert_called_once()
    mock_writer.write_note.assert_called_once()
    
    # Verify the note is scheduled
    mock_reminders.add_reminder.assert_called_once_with(
        title="Print Assessment",
        summary="Need to print assessment",
        reminder_time_str="2026-07-06 13:00:00",
        file_path=mock_writer.write_note.return_value
    )
    
    # Verify original note is deleted
    assert not note_file.exists()


@patch("app.destinations.review_manager.OllamaClassifier")
@patch("app.destinations.review_manager.ObsidianWriter")
def test_review_manager_manual_review(mock_writer_cls: MagicMock, mock_classifier_cls: MagicMock, tmp_path: Path) -> None:
    """Verifies manual review triggers routing when checkboxes are completed."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    
    queue_dir = vault_dir / "Classroom Voice Notes" / "Review Queue"
    queue_dir.mkdir(parents=True)
    
    manager = ReviewManager(str(vault_dir), settings_manager=MagicMock())
    
    # Mock classifier output
    mock_classifier = MagicMock()
    mock_classifier.classify.return_value = {
        "category": "student_note",
        "route": "local_student_note",
        "sensitivity": "student_sensitive",
        "title": "Alex Reading",
        "summary": "Alex is reading better",
        "confidence": 0.85
    }
    mock_classifier_cls.return_value = mock_classifier
    
    # Mock writer
    mock_writer = MagicMock()
    mock_writer.write_note.return_value = str(vault_dir / "Classroom Voice Notes" / "Student Notes" / "note_routed.md")
    mock_writer_cls.return_value = mock_writer
    
    # Place a fully-reviewed note
    note_content = """---
type: classroom-voice-note
confidence: 0.5
category: review_queue
created: 2026-07-06 12:00:00
duration_seconds: 10
---
# Title
## Transcript
Alex is reading better today.
## Review Status
- [x] Checked transcript
- [X] Edited for accuracy
"""
    note_file = queue_dir / "note_reviewed.md"
    note_file.write_text(note_content, encoding="utf-8")
    
    # Run scan
    manager.scan_queue()
    
    # Verify manual completion triggers routing and deletion
    mock_classifier.classify.assert_called_once()
    mock_writer.write_note.assert_called_once()
    assert not note_file.exists()
