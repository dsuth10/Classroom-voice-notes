import json
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
from app.audit.audit_logger import log_audit_event

class StudentIndexBuilder:
    def __init__(self, vault_path: str) -> None:
        self.vault_path = Path(vault_path)
        self.index_file = self.vault_path / "Classroom Voice Notes" / "Student Index.md"
        self.registry_file = self.vault_path / "Classroom Voice Notes" / "student_registry.json"

    def _load_registry(self) -> Dict[str, str]:
        """Loads ID-to-Name mapping from registry."""
        mapping = {}
        if not self.registry_file.exists():
            return mapping
        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                students = data.get("students", {})
                for name_key, student_info in students.items():
                    s_id = student_info.get("id")
                    display_name = student_info.get("display_name", name_key.capitalize())
                    if s_id:
                        mapping[s_id] = display_name
        except Exception as e:
            log_audit_event("INDEX_REGISTRY_LOAD_ERROR", "privacy", f"Failed to load registry: {e}")
        return mapping

    def _parse_note(self, file_path: Path) -> Dict[str, Any]:
        """Simple helper to extract YAML frontmatter from a markdown note."""
        frontmatter = {}
        try:
            content = file_path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---")
                if len(parts) >= 3:
                    yaml_str = parts[1]
                    current_key = None
                    for line in yaml_str.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("-") and current_key:
                            if not isinstance(frontmatter.get(current_key), list):
                                frontmatter[current_key] = []
                            frontmatter[current_key].append(line[1:].strip())
                        elif ":" in line:
                            key, val = line.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if val == "":
                                frontmatter[key] = []
                                current_key = key
                            else:
                                if val.lower() == "true":
                                    frontmatter[key] = True
                                elif val.lower() == "false":
                                    frontmatter[key] = False
                                else:
                                    # Simple parsing: remove quotes if present
                                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                        val = val[1:-1]
                                    frontmatter[key] = val
                                current_key = None
        except Exception as e:
            log_audit_event("INDEX_PARSE_NOTE_ERROR", "session", f"Failed to parse note {file_path.name}: {e}")
        return frontmatter

    def rebuild_index(self) -> None:
        """Scans the vault, groups notes by student ID, and builds the Student Index.md."""
        log_audit_event("INDEX_REBUILD_START", "session", "Starting Student Index rebuild")
        id_to_name = self._load_registry()
        
        # Mapping: student_id -> list of note info dicts
        student_notes: Dict[str, List[Dict[str, Any]]] = {}
        
        folders_to_scan = [
            "Student Notes",
            "Behaviour Notes",
            "Maths Notes",
            "English Notes",
            "Science Notes",
            "HASS Notes",
            "Digital Technologies Notes",
            "Design Technologies Notes",
            "Inbox",
            "Review Queue"
        ]
        
        base_dir = self.vault_path / "Classroom Voice Notes"
        for folder in folders_to_scan:
            target_folder = base_dir / folder
            if not target_folder.exists():
                continue
            
            for md_file in target_folder.glob("*.md"):
                fm = self._parse_note(md_file)
                students = fm.get("students", [])
                
                # Normalize string format if parsed as a flat comma separated string
                if isinstance(students, str):
                    students = [s.strip() for s in students.split(",") if s.strip()]
                    
                if not students:
                    continue
                    
                note_date = fm.get("date", "Unknown Date")
                note_category = fm.get("category", "General").replace("_", " ").title()
                note_title = fm.get("title", md_file.stem)
                
                # Make path relative to Vault Root for Obsidian link consistency
                # e.g., Classroom Voice Notes/Student Notes/file.md
                try:
                    rel_path = md_file.relative_to(self.vault_path).as_posix()
                except ValueError:
                    rel_path = md_file.name
                
                for s_id in students:
                    if s_id not in student_notes:
                        student_notes[s_id] = []
                    student_notes[s_id].append({
                        "path": rel_path,
                        "title": note_title,
                        "date": note_date,
                        "category": note_category
                    })
                    
        # Construct Markdown content
        now_str = datetime.now().strftime("%d %B %Y, %I:%M %p")
        lines = [
            "# Student Index",
            "",
            f"**Last Generated**: {now_str}",
            "",
            "This is a local, privacy-compliant index mapping anonymised student records to classroom observations, curriculum milestones, and behaviour events.",
            ""
        ]
        
        if not student_notes:
            lines.append("*No student notes found in the vault.*")
        else:
            # Sort students by name (or ID if name is unknown)
            sorted_students = sorted(
                student_notes.keys(),
                key=lambda s: id_to_name.get(s, s).lower()
            )
            
            for s_id in sorted_students:
                name = id_to_name.get(s_id, s_id)
                lines.append(f"## {name} ({s_id})")
                lines.append("")
                
                # Sort notes for this student by date descending
                notes = sorted(student_notes[s_id], key=lambda x: x["date"], reverse=True)
                for note in notes:
                    # Markdown link to file using vault-relative path
                    link = f"[[{note['path']}|{note['title']}]]"
                    lines.append(f"- **{note['date']}** — {link} ({note['category']})")
                lines.append("")
                
        # Write to Student Index.md
        try:
            self.index_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.index_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            log_audit_event("INDEX_REBUILD_SUCCESS", "session", f"Rebuilt Student Index with {len(student_notes)} student profiles")
        except Exception as e:
            log_audit_event("INDEX_REBUILD_ERROR", "session", f"Failed to save student index: {e}")
