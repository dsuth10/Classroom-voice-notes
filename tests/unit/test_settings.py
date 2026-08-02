from pathlib import Path
from unittest import mock
import pytest
from app.config.settings import SettingsManager

@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Fixture to mock app config path to a temporary folder."""
    config_file = tmp_path / "settings.json"
    with mock.patch("app.config.settings.get_config_path", return_value=config_file):
        yield tmp_path

def test_settings_initialization_defaults(temp_config_dir: Path) -> None:
    """Tests that default settings are created if settings.json doesn't exist."""
    manager = SettingsManager()
    assert manager.get("obsidian_vault_path") == ""
    assert manager.get("recording_limit_seconds") == 60
    assert manager.get("ollama_url") == "http://localhost:11434"
    assert manager.config_path.exists()

def test_settings_save_and_load(temp_config_dir: Path) -> None:
    """Tests that modifying and saving settings persists to settings.json."""
    manager = SettingsManager()
    manager.set("obsidian_vault_path", "C:/Vault")
    manager.set("recording_limit_seconds", 120)
    
    # Create a new manager instance to verify disk read
    new_manager = SettingsManager()
    assert new_manager.get("obsidian_vault_path") == "C:/Vault"
    assert new_manager.get("recording_limit_seconds") == 120

def test_nested_settings_defaults(temp_config_dir: Path) -> None:
    """Tests that default nested settings are correctly resolved."""
    manager = SettingsManager()
    assert manager.get("wake_word.engine") == "openwakeword"
    assert manager.get("wake_word.enabled") is True
    assert manager.get("spoken_commands.enabled") is False
    assert manager.get("audio.sample_rate") == 16000
    assert manager.get("recording.hard_cap_seconds") == 60

def test_nested_settings_save_and_load(temp_config_dir: Path) -> None:
    """Tests that nested settings values can be set and persist correctly."""
    manager = SettingsManager()
    manager.set("wake_word.engine", "manual_only")
    manager.set("wake_word.enabled", False)
    manager.set("audio.sample_rate", 22050)
    
    new_manager = SettingsManager()
    assert new_manager.get("wake_word.engine") == "manual_only"
    assert new_manager.get("wake_word.enabled") is False
    assert new_manager.get("audio.sample_rate") == 22050


def test_settings_get_default_fallback(temp_config_dir: Path) -> None:
    """Tests that get() returns the provided default fallback when a key does not exist."""
    manager = SettingsManager()
    assert manager.get("non_existent_key", "fallback_val") == "fallback_val"
    assert manager.get("nested.non_existent.key", "fallback_nested") == "fallback_nested"
    assert manager.get("non_existent_key_no_default") is None

def test_sharing_mode_defaults_and_validation(temp_config_dir: Path) -> None:
    """Tests Phase 3 sharing mode defaults and validation."""
    manager = SettingsManager()
    assert manager.get("external_agent.sharing_mode") == "off"
    assert manager.external_sharing_mode() == "off"
    assert manager.get("external_agent.include_full_transcript") is False
    assert manager.get("external_agent.default_item_kind") == "record_only"

    # Set valid mode
    manager.set("external_agent.sharing_mode", "review_all")
    assert manager.external_sharing_mode() == "review_all"

    # Set invalid mode -> fails closed to off
    manager.set("external_agent.sharing_mode", "invalid_mode")
    assert manager.external_sharing_mode() == "off"

def test_sharing_mode_migration(temp_config_dir: Path) -> None:
    """Tests that legacy enabled flag migrates correctly to sharing_mode."""
    import json
    config_file = temp_config_dir / "settings.json"
    
    # Save legacy config with enabled=True
    legacy_data = {"external_agent": {"enabled": True}}
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)
        
    manager = SettingsManager()
    assert manager.external_sharing_mode() == "safe_auto"

    # Save legacy config with enabled=False
    legacy_disabled = {"external_agent": {"enabled": False}}
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(legacy_disabled, f)
        
    manager_disabled = SettingsManager()
    assert manager_disabled.external_sharing_mode() == "off"


def test_source_device_id_fresh_and_persistent(temp_config_dir: Path) -> None:
    """Tests that a fresh load creates and persists a stable source_device_id across instances."""
    manager1 = SettingsManager()
    device_id1 = manager1.get("external_agent.source_device_id")
    assert device_id1 is not None
    assert device_id1.startswith("cvn-device-")

    manager2 = SettingsManager()
    device_id2 = manager2.get("external_agent.source_device_id")
    assert device_id2 == device_id1


def test_source_device_id_migration_repair(temp_config_dir: Path) -> None:
    """Tests that settings file with an empty source_device_id is repaired and saved."""
    import json
    config_file = temp_config_dir / "settings.json"
    legacy_data = {"external_agent": {"source_device_id": "", "sharing_mode": "review_all"}}
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    manager = SettingsManager()
    repaired_id = manager.get("external_agent.source_device_id")
    assert repaired_id is not None
    assert repaired_id.startswith("cvn-device-")

    new_manager = SettingsManager()
    assert new_manager.get("external_agent.source_device_id") == repaired_id


def test_save_failure_disables_sharing(temp_config_dir: Path) -> None:
    """Tests that persistence failure disables sharing mode safely."""
    manager = SettingsManager()
    with mock.patch.object(manager, "_atomic_save_json", return_value=False):
        manager.set("external_agent.sharing_mode", "review_all")
        assert manager.external_sharing_mode() == "off"
        assert manager.get("external_agent.enabled") is False


