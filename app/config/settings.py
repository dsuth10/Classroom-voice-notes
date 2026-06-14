import json
import os
from typing import Any, Dict
from pathlib import Path
from dotenv import load_dotenv
from app.utils.paths import get_config_path, get_default_whisper_bin_dir

# Load environment variables from .env if present
load_dotenv()

# Absolute project root — two levels up from this file (app/config/settings.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_SETTINGS: Dict[str, Any] = {
    "obsidian_vault_path": "",
    "porcupine_access_key": "",
    "porcupine_keywords": {},  # maps display name to .ppn path
    "whisper_bin_path": str(get_default_whisper_bin_dir() / "whisper.exe"),
    "whisper_model_path": str(get_default_whisper_bin_dir() / "ggml-base.en.bin"),
    "recording_limit_seconds": 60,
    "ollama_url": "http://localhost:11434",
    "fast_model": "qwen3.5:latest",
    "careful_model": "phi4:14b",
    "telegram_token": "",
    "telegram_chat_id": "",
    "telegram_enabled": False,
    "wake_word": {
        "engine": "openwakeword",
        "enabled": True,
        "phrase": "Joshua note",
        "model_path": str(_PROJECT_ROOT / "models" / "wakewords" / "joshua_note.onnx"),
        "threshold": 0.5,
        "cooldown_seconds": 2.0,
    },
    "spoken_commands": {
        "enabled": False,
        "engine": "vosk",
        "model_path": str(_PROJECT_ROOT / "models" / "vosk" / "vosk-model-small-en"),
        "grammar_keywords": ["save", "cancel", "stop", "discard"],
        "command_cooldown_seconds": 2.0,
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "chunk_size": 1280,
        "pre_roll_seconds": 1.5,
    },
    "recording": {
        "hard_cap_seconds": 60,
        "manual_controls_enabled": True,
    },
}

def deep_update(d: Dict[str, Any], u: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively updates dictionary d with dictionary u."""
    for k, v in u.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            d[k] = deep_update(d[k], v)
        else:
            d[k] = v
    return d

class SettingsManager:
    def __init__(self) -> None:
        self.config_path: Path = get_config_path()
        self.settings: Dict[str, Any] = self.load_settings()

    def load_settings(self) -> Dict[str, Any]:
        """Loads settings from settings.json, falling back to defaults if missing or corrupted."""
        import copy
        if not self.config_path.exists():
            default_copy = copy.deepcopy(DEFAULT_SETTINGS)
            self.save_settings(default_copy)
            return default_copy
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure all default keys exist by doing a deep update
                updated = copy.deepcopy(DEFAULT_SETTINGS)
                if isinstance(data, dict):
                    updated = deep_update(updated, data)
                return updated
        except Exception:
            return copy.deepcopy(DEFAULT_SETTINGS)

    def save_settings(self, new_settings: Dict[str, Any]) -> None:
        """Saves configuration to settings.json."""
        import copy
        self.settings = copy.deepcopy(new_settings)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def get(self, key: str) -> Any:
        """Retrieves a configuration parameter, prioritizing environment variable overrides for keys.
        
        Supports dot-separated paths for nested access (e.g. 'wake_word.engine').
        """
        if key == "porcupine_access_key":
            env_key = os.getenv("PORCUPINE_ACCESS_KEY")
            if env_key:
                return env_key

        parts = key.split(".")
        
        # Try to resolve from self.settings
        val: Any = self.settings
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                # Fallback to DEFAULT_SETTINGS
                import copy
                val = copy.deepcopy(DEFAULT_SETTINGS)
                for p in parts:
                    if isinstance(val, dict) and p in val:
                        val = val[p]
                    else:
                        return None
                return val
        return val

    def set(self, key: str, value: Any) -> None:
        """Sets a configuration parameter and saves changes.
        
        Supports dot-separated paths for nested access (e.g. 'wake_word.engine').
        """
        parts = key.split(".")
        val = self.settings
        for part in parts[:-1]:
            if part not in val or not isinstance(val[part], dict):
                val[part] = {}
            val = val[part]
        val[parts[-1]] = value
        self.save_settings(self.settings)

