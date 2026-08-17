import json
import os
from typing import Any, Dict
from pathlib import Path
from urllib.parse import urlparse
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
    "agents": {
        "enabled": False,
        "telegram_token": "",
        "default_agent": "hermes",
        "agents": {
            "hermes": {
                "display_name": "Hermes",
                "chat_id": "",
                "description": "General-purpose AI assistant. Research, planning, professional tasks.",
                "enabled": True
            },
            "openclaw": {
                "display_name": "OpenClaw",
                "chat_id": "",
                "description": "Specialised agent. Code, technical, and analytical tasks.",
                "enabled": True
            }
        }
    },
    "external_agent": {
        "enabled": False,
        "sharing_mode": "off",
        "include_full_transcript": False,
        "default_item_kind": "record_only",
        "trusted_pause_on_high_risk": True,
        "review_retention_days": 30,
        "endpoint_url": "",
        "hmac_secret_ref": "cvn_hmac_secret",
        "bearer_token_ref": "cvn_bearer_token",
        "target_agent_default": "openclaw",
        "source_device_id": "",
        "allowed_target_agents": ["openclaw"],
        "allowed_endpoint_domains": ["supabase.co"],
        "policy_gate_version": "1.0.0",
        "max_payload_bytes": 65536
    },
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
        "device_index": None,
        "earcons_enabled": True,
        "earcons_volume": 0.7,
    },
    "recording": {
        "hard_cap_seconds": 60,
        "manual_controls_enabled": True,
    },
    "system": {
        "minimize_to_tray": True,
        "hotkey_enabled": True,
        "hotkey_sequence": "Win+Shift+V",
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

    def _atomic_save_json(self, filepath: Path, data: Dict[str, Any]) -> bool:
        """Writes JSON data atomically to filepath using a temporary file in the same directory."""
        import uuid
        tmp_file = filepath.with_name(f"{filepath.name}.tmp.{uuid.uuid4().hex[:8]}")
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, filepath)
            return True
        except Exception as e:
            print(f"Failed to atomically save settings: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass
            return False

    def _ensure_source_device_id(self, data: Dict[str, Any]) -> None:
        """Ensures external_agent.source_device_id is populated and atomically persisted."""
        import uuid
        ext_agent = data.get("external_agent")
        if not isinstance(ext_agent, dict):
            ext_agent = {}
            data["external_agent"] = ext_agent

        dev_id = ext_agent.get("source_device_id")
        legacy_defaults = {"cvn-device-default", "cvn-device-local-default", "cvn-device"}
        if not dev_id or not isinstance(dev_id, str) or not dev_id.strip() or dev_id in legacy_defaults:
            ext_agent["source_device_id"] = f"cvn-device-{uuid.uuid4().hex[:12]}"

        save_ok = self._atomic_save_json(self.config_path, data)
        if not save_ok:
            ext_agent["sharing_mode"] = "off"
            ext_agent["enabled"] = False

    def load_settings(self) -> Dict[str, Any]:
        """Loads settings from settings.json, falling back to defaults if missing or corrupted."""
        import copy
        if not self.config_path.exists():
            default_copy = copy.deepcopy(DEFAULT_SETTINGS)
            self._ensure_source_device_id(default_copy)
            return default_copy

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            fallback = copy.deepcopy(DEFAULT_SETTINGS)
            self._ensure_source_device_id(fallback)
            return fallback

        # Perform migration of old flat Telegram settings to nested agents structure if present
        if isinstance(data, dict):
            old_enabled = data.get("telegram_enabled")
            old_token = data.get("telegram_token")
            old_chat_id = data.get("telegram_chat_id")

            if (old_enabled is not None or old_token is not None or old_chat_id is not None) and "agents" not in data:
                data["agents"] = {
                    "enabled": old_enabled if old_enabled is not None else False,
                    "telegram_token": old_token if old_token is not None else "",
                    "default_agent": "hermes",
                    "agents": {
                        "hermes": {
                            "display_name": "Hermes",
                            "chat_id": old_chat_id if old_chat_id is not None else "",
                            "description": "General-purpose AI assistant. Research, planning, professional tasks.",
                            "enabled": True
                        },
                        "openclaw": {
                            "display_name": "OpenClaw",
                            "chat_id": "",
                            "description": "Specialised agent. Code, technical, and analytical tasks.",
                            "enabled": True
                        }
                    }
                }
                data.pop("telegram_enabled", None)
                data.pop("telegram_token", None)
                data.pop("telegram_chat_id", None)

            # Migration: external_agent.sharing_mode from legacy enabled flag
            ext_agent = data.get("external_agent")
            valid_modes = {"off", "safe_auto", "review_all", "trusted_auto"}
            if isinstance(ext_agent, dict):
                existing_mode = ext_agent.get("sharing_mode")
                if existing_mode in valid_modes:
                    pass  # Existing valid mode wins
                else:
                    old_enabled = ext_agent.get("enabled")
                    if old_enabled is True:
                        ext_agent["sharing_mode"] = "safe_auto"
                    else:
                        ext_agent["sharing_mode"] = "off"

        # Ensure all default keys exist by doing a deep update
        updated = copy.deepcopy(DEFAULT_SETTINGS)
        if isinstance(data, dict):
            updated = deep_update(updated, data)

        self._ensure_source_device_id(updated)

        # Keep derived enabled flag in sync with sharing_mode
        if isinstance(updated.get("external_agent"), dict):
            mode = updated["external_agent"].get("sharing_mode", "off")
            updated["external_agent"]["enabled"] = (mode != "off")
        return updated


    def external_sharing_mode(self) -> str:
        """Returns validated external sharing mode ('off', 'safe_auto', 'review_all', 'trusted_auto')."""
        mode = self.get("external_agent.sharing_mode", "off")
        valid_modes = {"off", "safe_auto", "review_all", "trusted_auto"}
        if isinstance(mode, str) and mode in valid_modes:
            return mode
        return "off"

    def external_sharing_enabled(self) -> bool:
        """Returns True if external sharing mode is active (not 'off')."""
        return self.external_sharing_mode() != "off"

    def save_settings(self, new_settings: Dict[str, Any]) -> None:
        """Saves configuration to settings.json atomically."""
        import copy
        self.settings = copy.deepcopy(new_settings)
        save_ok = self._atomic_save_json(self.config_path, self.settings)
        if not save_ok and isinstance(self.settings.get("external_agent"), dict):
            self.settings["external_agent"]["sharing_mode"] = "off"
            self.settings["external_agent"]["enabled"] = False


    def get(self, key: str, default: Any = None) -> Any:
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
                        return default
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

        # Sync legacy external_agent.enabled and external_agent.sharing_mode
        if key == "external_agent.enabled":
            ext = self.settings.get("external_agent", {})
            if isinstance(ext, dict):
                if value is True and ext.get("sharing_mode", "off") == "off":
                    ext["sharing_mode"] = "safe_auto"
                elif value is False:
                    ext["sharing_mode"] = "off"
        elif key == "external_agent.sharing_mode":
            ext = self.settings.get("external_agent", {})
            if isinstance(ext, dict):
                valid_modes = {"off", "safe_auto", "review_all", "trusted_auto"}
                mode = value if isinstance(value, str) and value in valid_modes else "off"
                ext["sharing_mode"] = mode
                ext["enabled"] = (mode != "off")
        elif key == "ollama_url":
            if not is_loopback_url(str(value)):
                raise ValueError(f"Ollama URL must point to local loopback (localhost, 127.0.0.1, ::1). Got: {value}")

        self.save_settings(self.settings)

def is_loopback_url(url: str) -> bool:
    """Returns True if the URL points strictly to a local loopback address (localhost, 127.0.0.1, ::1)."""
    if not url:
        return False
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        hostname = (parsed.hostname or "").lower()
        return hostname in {"localhost", "127.0.0.1", "::1"}
    except Exception:
        return False


