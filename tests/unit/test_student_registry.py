import json
from pathlib import Path
from app.privacy.student_registry import StudentRegistry

def test_student_registry_lifecycle(tmp_path: Path) -> None:
    """Verifies that StudentRegistry handles load, save, lookup, registration, and bulk import correctly."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    
    registry = StudentRegistry(str(vault_dir))
    
    # Check blank init
    assert len(registry.data["students"]) == 0
    assert registry.data["next_id"] == 1
    
    # Register student
    student_id = registry.register("Alex")
    assert student_id == "STU-001"
    assert registry.lookup("Alex") == "STU-001"
    assert registry.lookup("alex") == "STU-001"  # Case insensitivity
    assert registry.lookup("ALEX") == "STU-001"
    
    # Register another
    student_id_2 = registry.register("Jordan")
    assert student_id_2 == "STU-002"
    
    # Reload and check persistence
    registry2 = StudentRegistry(str(vault_dir))
    assert registry2.lookup("Alex") == "STU-001"
    assert registry2.lookup("Jordan") == "STU-002"
    
    # Anonymise list (with auto-registration of unknown names)
    ids = registry2.anonymise_list(["Alex", "Jordan", "Charlie"])
    assert ids == ["STU-001", "STU-002", "STU-003"]
    assert registry2.lookup("Charlie") == "STU-003"
    
    # Bulk import
    registry3 = StudentRegistry(str(vault_dir))
    import_map = registry3.bulk_import(["Dave", "Eve"])
    assert import_map["Dave"] == "STU-004"
    assert import_map["Eve"] == "STU-005"
    assert registry3.lookup("dave") == "STU-004"
