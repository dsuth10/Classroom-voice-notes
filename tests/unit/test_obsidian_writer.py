from pathlib import Path
from app.destinations.obsidian_writer import ObsidianWriter

def test_obsidian_writer_creates_note_and_folders(tmp_path: Path) -> None:
    """Verifies that ObsidianWriter auto-creates directories and formats frontmatter correctly."""
    writer = ObsidianWriter(str(tmp_path))
    
    # Write a behaviour note
    file_path_str = writer.write_note(
        title="Student Misbehaviour",
        transcript="Alex threw a paper airplane.",
        category="behaviour_note",
        route="local_behaviour_note",
        sensitivity="student_sensitive",
        duration_seconds=12,
        audio_file_path="C:/temp/audio.wav",
        telegram_allowed=False,
        confidence=0.98
    )
    
    file_path = Path(file_path_str)
    assert file_path.exists()
    
    # Verify subfolder created: Classroom Voice Notes/Behaviour Notes
    expected_dir = tmp_path / "Classroom Voice Notes" / "Behaviour Notes"
    assert expected_dir.exists()
    assert file_path.parent == expected_dir
    
    # Check file contents
    content = file_path.read_text(encoding="utf-8")
    assert "type: classroom-voice-note" in content
    assert "route: local_behaviour_note" in content
    assert "sensitivity: student_sensitive" in content
    assert "category: behaviour_note" in content
    assert "telegram_allowed: false" in content
    assert "Alex threw a paper airplane." in content
