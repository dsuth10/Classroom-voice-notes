from app.destinations.note_templates import NoteTemplates

def test_render_student_note() -> None:
    """Verifies that rendering a student note correctly injects student IDs and category layout."""
    base_fm = {
        "type": "classroom-voice-note",
        "route": "local_student_note",
        "sensitivity": "student_sensitive",
        "category": "student_note",
        "confidence": 0.9
    }
    
    fields = {
        "students": ["STU-001", "STU-002"],
        "observation_type": "academic progress"
    }
    
    rendered = NoteTemplates.render(
        category="student_note",
        title="Student Note",
        now_str="06 July 2026, 04:30 PM",
        transcript="Alex and Jordan did well.",
        base_frontmatter=base_fm,
        category_fields=fields
    )
    
    # Check frontmatter YAML
    assert "category: student_note" in rendered
    assert "students:" in rendered
    assert "  - STU-001" in rendered
    assert "  - STU-002" in rendered
    assert "observation_type: academic progress" in rendered
    
    # Check body sections
    assert "# Student Note — 06 July 2026, 04:30 PM" in rendered
    assert "## Observation Details" in rendered
    assert "- **Observation Type**: academic progress" in rendered
    assert "- **Students Involved (IDs)**: STU-001, STU-002" in rendered


def test_render_maths_note() -> None:
    """Verifies that rendering a maths note formats the curriculum details block properly."""
    base_fm = {
        "type": "classroom-voice-note",
        "route": "local_maths_note",
        "sensitivity": "student_sensitive",
        "category": "maths_note",
        "confidence": 0.8
    }
    
    fields = {
        "students": ["STU-001"],
        "strand": "Number and Algebra",
        "misconception_type": "place value confusion",
        "year_level": "Year 5"
    }
    
    rendered = NoteTemplates.render(
        category="maths_note",
        title="Maths Place Value",
        now_str="06 July 2026, 04:30 PM",
        transcript="Alex was confused by tens.",
        base_frontmatter=base_fm,
        category_fields=fields
    )
    
    # Check frontmatter
    assert "strand: Number and Algebra" in rendered
    assert "misconception_type: place value confusion" in rendered
    
    # Check body
    assert "## Curriculum Context" in rendered
    assert "- **Subject**: Mathematics" in rendered
    assert "- **Year Level**: Year 5" in rendered
    assert "- **Strand**: Number and Algebra" in rendered
    assert "- **Key Misconception**: place value confusion" in rendered
