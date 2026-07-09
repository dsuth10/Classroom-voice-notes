import re
import json
from datetime import datetime, timezone
from app.destinations.payload_builder import build_payload, generate_task_id

def test_generate_task_id() -> None:
    dt = datetime(2026, 7, 9, 10, 30, 45)
    task_id = generate_task_id(dt)
    assert re.match(r"^CVN-20260709-103045-[A-Z0-9]{4}$", task_id)

def test_build_payload_success() -> None:
    classification = {
        "title": "Clean whiteboards",
        "summary": "Use microfiber cloth to clean all whiteboards in Room 5.",
        "category": "agent_task",
        "category_fields": {
            "priority": "high"
        }
    }
    
    payload, json_str, payload_hash = build_payload(
        classification_data=classification,
        source_device_id="test-pc-001",
        target_agent="hermes",
        checks_passed=["category_agent_task", "no_student_registry_match"]
    )
    
    # Verify values
    assert payload["schema_version"] == "cvn.agent_task.v1"
    assert payload["source_device_id"] == "test-pc-001"
    assert payload["target_agent"] == "hermes"
    assert payload["privacy"]["classification"] == "non_sensitive"
    assert payload["privacy"]["checks_passed"] == ["category_agent_task", "no_student_registry_match"]
    
    assert payload["task"]["title"] == "Clean whiteboards"
    assert payload["task"]["instructions"] == "Use microfiber cloth to clean all whiteboards in Room 5."
    assert payload["task"]["priority"] == "high"
    
    assert "nonce" in payload
    assert "idempotency_key" in payload
    assert "signed_at" in payload
    
    # Verify deterministic serialization
    loaded = json.loads(json_str)
    assert loaded == payload
    
    # Hash is SHA256 of the exact serialization
    import hashlib
    expected_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
    assert payload_hash == expected_hash

def test_build_payload_fallback_defaults() -> None:
    classification = {}
    
    payload, _, _ = build_payload(
        classification_data=classification,
        source_device_id="device-abc",
        target_agent="openclaw",
        checks_passed=[]
    )
    
    assert payload["task"]["title"] == "Unnamed Agent Task"
    assert payload["task"]["instructions"] == "No instructions provided."
    assert payload["task"]["priority"] == "normal"
