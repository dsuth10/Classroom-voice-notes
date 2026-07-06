import json
from pathlib import Path
from app.destinations.student_index import StudentIndexBuilder
from app.privacy.student_registry import StudentRegistry

def test_student_index_rebuild(tmp_path: Path) -> None:
    """Verifies that StudentIndexBuilder aggregates notes by student and resolves anonymised names correctly."""
    # Setup folders
    vault_dir = tmp_path / "vault"
    cvn_dir = vault_dir / "Classroom Voice Notes"
    cvn_dir.mkdir(parents=True)
    
    # 1. Register some students
    registry = StudentRegistry(str(vault_dir))
    alex_id = registry.register("Alex") # STU-001
    jordan_id = registry.register("Jordan") # STU-002
    
    # 2. Write some dummy notes with student IDs in frontmatter
    maths_dir = cvn_dir / "Maths Notes"
    maths_dir.mkdir()
    
    note1 = maths_dir / "note1.md"
    note1.write_text("""---
type: classroom-voice-note
category: maths_note
date: 2026-07-06
title: Place Value Struggle
students:
  - STU-001
  - STU-002
---
## Transcript
Struggled with numbers.
""", encoding="utf-8")

    behaviour_dir = cvn_dir / "Behaviour Notes"
    behaviour_dir.mkdir()
    
    note2 = behaviour_dir / "note2.md"
    note2.write_text("""---
type: classroom-voice-note
category: behaviour_note
date: 2026-07-05
title: Disruption
students:
  - STU-001
---
## Transcript
Talking in class.
""", encoding="utf-8")

    # Rebuild index
    builder = StudentIndexBuilder(str(vault_dir))
    builder.rebuild_index()
    
    # Assert Student Index.md exists
    index_file = cvn_dir / "Student Index.md"
    assert index_file.exists()
    
    content = index_file.read_text(encoding="utf-8")
    
    # Verify index contains resolved display names and links
    assert "## Alex (STU-001)" in content
    assert "## Jordan (STU-002)" in content
    
    # Check that links point correctly
    assert "- **2026-07-06** — [[Classroom Voice Notes/Maths Notes/note1.md|Place Value Struggle]] (Maths Note)" in content
    assert "- **2026-07-05** — [[Classroom Voice Notes/Behaviour Notes/note2.md|Disruption]] (Behaviour Note)" in content
