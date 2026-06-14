import os
from pathlib import Path

def get_app_data_dir() -> Path:
    """Returns the application data directory in local AppData on Windows."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data) / "ClassroomVoiceNotes"
    else:
        base_dir = Path.home() / ".classroom-voice-notes"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

def get_config_path() -> Path:
    """Returns the path to settings.json."""
    return get_app_data_dir() / "settings.json"

def get_audit_log_path() -> Path:
    """Returns the path to audit.log."""
    log_dir = get_app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "audit.log"

def get_temp_audio_dir() -> Path:
    """Returns the path for temporary audio recordings."""
    audio_dir = get_app_data_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir

def get_default_whisper_bin_dir() -> Path:
    """Returns the default subfolder under the project root for whisper.cpp binaries."""
    project_root = Path(__file__).resolve().parent.parent.parent
    bin_dir = project_root / "bin" / "whisper"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return bin_dir
