from pathlib import Path
from app.destinations.obsidian_writer import ObsidianWriter

def test_obsidian_writer_creates_note_and_folders(tmp_path: Path) -> None:
    """Verifies that ObsidianWriter auto-creates directories and formats frontmatter correctly."""
    writer = ObsidianWriter(str(tmp_path))
    
    classification_data = {
        "title": "Student Misbehaviour",
        "category": "behaviour_note",
        "route": "local_behaviour_note",
        "sensitivity": "student_sensitive",
        "telegram_allowed": False,
        "confidence": 0.98,
        "tags": ["classroom-note", "behaviour-note"],
    }
    
    file_path_str = writer.write_note(
        classification_data=classification_data,
        transcript="Alex threw a paper airplane.",
        duration_seconds=12,
        audio_file_path="C:/temp/audio.wav"
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


def test_obsidian_writer_student_anonymisation(tmp_path: Path) -> None:
    """Verifies that ObsidianWriter resolves student names to anonymised IDs and renders the custom template."""
    writer = ObsidianWriter(str(tmp_path))
    
    classification_data = {
        "title": "Maths Addition Struggle",
        "category": "maths_note",
        "route": "local_maths_note",
        "sensitivity": "student_sensitive",
        "telegram_allowed": False,
        "confidence": 0.95,
        "category_fields": {
            "students_mentioned": ["Charlie", "Jordan"],
            "strand": "Number and Algebra",
            "year_level": "Year 5",
            "misconception_type": "carrying error"
        }
    }
    
    file_path_str = writer.write_note(
        classification_data=classification_data,
        transcript="Charlie and Jordan struggled with carrying digits.",
        duration_seconds=30
    )
    
    file_path = Path(file_path_str)
    assert file_path.exists()
    
    content = file_path.read_text(encoding="utf-8")
    
    # Check anonymised student IDs in frontmatter
    assert "students:" in content
    assert "  - STU-001" in content
    assert "  - STU-002" in content
    assert "Charlie" not in content.split("---")[1]  # Ensure real names NOT in frontmatter
    
    # Check maths-specific body rendering
    assert "## Curriculum Context" in content
    assert "- **Subject**: Mathematics" in content
    assert "- **Year Level**: Year 5" in content
    assert "- **Strand**: Number and Algebra" in content
    assert "- **Key Misconception**: carrying error" in content
    assert "- **Students Involved (IDs)**: STU-001, STU-002" in content

