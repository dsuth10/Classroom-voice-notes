import json
from datetime import datetime
from typing import Any, Dict
from app.utils.paths import get_audit_log_path

def log_audit_event(event_type: str, session_id: str, message: str, metadata: Dict[str, Any] | None = None) -> None:
    """Appends a structured JSON event to the audit log."""
    log_path = get_audit_log_path()
    
    event: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "session_id": session_id,
        "message": message,
        "metadata": metadata or {}
    }
    
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"Failed to write audit log: {e}")
