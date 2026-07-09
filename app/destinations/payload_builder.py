import json
import hashlib
import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

def generate_task_id(dt: datetime) -> str:
    """Generates a task_id following the pattern CVN-YYYYMMDD-HHMMSS-XXXX."""
    date_str = dt.strftime("%Y%m%d-%H%M%S")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"CVN-{date_str}-{suffix}"

def build_payload(
    classification_data: Dict[str, Any],
    source_device_id: str,
    target_agent: str,
    checks_passed: List[str],
    policy_gate_version: str = "1.0.0"
) -> Tuple[Dict[str, Any], str, str]:
    """Constructs a cvn.agent_task.v1 payload dictionary and its deterministic serialisation.
    
    Returns:
        (payload_dict, deterministic_json_str, payload_hash)
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    task_id = generate_task_id(now)
    idempotency_key = str(uuid.uuid4())
    nonce = str(uuid.uuid4())
    
    # Extract task details safely, ensuring NO raw transcript is included
    task_source = classification_data.get("task", {})
    title = task_source.get("title") or classification_data.get("title") or "Unnamed Agent Task"
    instructions = task_source.get("instructions") or classification_data.get("summary") or "No instructions provided."
    priority = task_source.get("priority") or classification_data.get("category_fields", {}).get("priority") or "normal"
    
    # Ensure priority is clean and lowercase
    priority = str(priority).lower()
    if priority not in ("low", "normal", "high"):
        priority = "normal"

    payload: Dict[str, Any] = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": task_id,
        "created_at": now_iso,
        "source": "classroom_voice_notes",
        "source_device_id": source_device_id,
        "target_agent": target_agent,
        "privacy": {
            "classification": "non_sensitive",
            "policy_gate_version": policy_gate_version,
            "checks_passed": sorted(checks_passed)
        },
        "task": {
            "title": title.strip(),
            "instructions": instructions.strip(),
            "priority": priority
        },
        "redactions_applied": sorted(classification_data.get("redactions_applied", [])),
        "signed_at": now_iso,
        "nonce": nonce,
        "idempotency_key": idempotency_key
    }
    
    # Deterministic serialisation
    json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
    
    return payload, json_str, payload_hash
