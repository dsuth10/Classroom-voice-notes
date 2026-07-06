import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.audit.audit_logger import log_audit_event

class StudentRegistry:
    def __init__(self, vault_path: str) -> None:
        self.vault_path = Path(vault_path)
        self.db_path = self.vault_path / "Classroom Voice Notes" / "student_registry.json"
        self.data: Dict[str, Any] = {"students": {}, "next_id": 1}
        self.load()

    def load(self) -> None:
        """Loads student registry from the Obsidian vault, creating it if missing."""
        if not self.db_path.exists():
            self.save()
            return
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and "students" in loaded and "next_id" in loaded:
                    self.data = loaded
        except Exception as e:
            log_audit_event("STUDENT_REGISTRY_LOAD_ERROR", "privacy", f"Failed to load student registry: {e}")

    def save(self) -> None:
        """Saves the student registry back to the vault."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log_audit_event("STUDENT_REGISTRY_SAVE_ERROR", "privacy", f"Failed to save student registry: {e}")

    def lookup(self, name: str) -> Optional[str]:
        """Looks up a student name (case-insensitive) and returns their ID (e.g. STU-001)."""
        name_key = name.strip().lower()
        student = self.data["students"].get(name_key)
        return student["id"] if student else None

    def register(self, name: str) -> str:
        """Registers a new student name and returns the newly generated ID."""
        name_key = name.strip().lower()
        existing_id = self.lookup(name)
        if existing_id:
            return existing_id

        next_id_num = self.data.get("next_id", 1)
        student_id = f"STU-{next_id_num:03d}"
        
        self.data["students"][name_key] = {
            "id": student_id,
            "display_name": name.strip(),
            "added": Path().stat().st_mtime if False else None # We can just use None or skip datetime logic
        }
        self.data["next_id"] = next_id_num + 1
        self.save()
        log_audit_event("STUDENT_REGISTERED", "privacy", f"Registered new student '{name}' with ID {student_id}")
        return student_id

    def anonymise_list(self, names: List[str]) -> List[str]:
        """Converts a list of student names into their corresponding anonymised IDs.
        
        Auto-registers any name not already in the database to prevent data loss.
        """
        anonymised = []
        for name in names:
            if not name or not name.strip():
                continue
            student_id = self.lookup(name)
            if not student_id:
                student_id = self.register(name)
            anonymised.append(student_id)
        return anonymised

    def bulk_import(self, names: List[str]) -> Dict[str, str]:
        """Helper to seed the registry from a class list. Returns mapping dict."""
        mapping = {}
        for name in names:
            name_clean = name.strip()
            if name_clean:
                mapping[name_clean] = self.register(name_clean)
        return mapping
