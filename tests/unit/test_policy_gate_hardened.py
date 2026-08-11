import json
import re
from pathlib import Path
import pytest
from app.ollama_router.policy_gate import PolicyGate
from app.privacy.student_registry import StudentRegistry

@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    # Setup temporary vault with student registry
    vault_dir = tmp_path / "ObsidianVault"
    registry_dir = vault_dir / "Classroom Voice Notes"
    registry_dir.mkdir(parents=True, exist_ok=True)
    
    registry_file = registry_dir / "student_registry.json"
    registry_data = {
        "students": {
            "sam jones": {"id": "STU-001", "display_name": "Sam Jones"},
            "will": {"id": "STU-002", "display_name": "Will"},
            "mary-jane": {"id": "STU-003", "display_name": "Mary-Jane"}
        },
        "next_id": 4
    }
    
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump(registry_data, f)
        
    return vault_dir

@pytest.fixture
def default_payload() -> dict:
    return {
        "schema_version": "cvn.agent_task.v1",
        "task_id": "CVN-20260709-120000-ABCD",
        "source_device_id": "device-001",
        "target_agent": "hermes",
        "task": {
            "title": "Clean desks",
            "instructions": "Ensure all students leave their desks clean before leaving the classroom.",
            "priority": "normal"
        }
    }

@pytest.fixture
def default_config() -> dict:
    return {
        "max_payload_bytes": 65536,
        "allowed_target_agents": ["hermes", "openclaw", "auto"],
        "allowed_endpoint_domains": ["supabase.co"]
    }

def test_policy_gate_all_pass(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    allowed, checks = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="Please clean all the desks before leaving.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    
    assert allowed is True
    assert "category_agent_task" in checks
    assert "no_student_registry_match" in checks
    assert "endpoint_domain_allowlisted" in checks

def test_policy_gate_category_blocked(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    allowed, _ = gate.is_external_dispatch_allowed(
        category="student_note",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="Please clean all the desks.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_policy_gate_sensitivity_blocked(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="student_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="Please clean all the desks.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_policy_gate_student_registry_load_failure(default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="Please clean all the desks.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path="C:/this/path/does/not/exist/at/all/99999",
        config=default_config
    )
    # Fail closed on missing/invalid registry load
    assert allowed is False

def test_policy_gate_student_name_exact_word_match_blocks(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    # 1. Matches "Sam Jones" in transcript -> Blocks
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="Tell Sam Jones to clean the desk.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

    # 2. Matches "Will" as standalone word -> Blocks
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="Ask Will to help.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_policy_gate_student_name_false_positives_allowed(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    # "willing" contains "will" but is not a standalone name -> Allowed!
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Ensure desks are clean."},
        transcript="I am willing to help clean the whiteboard.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is True

def test_policy_gate_forbidden_keyword_blocks(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    # "medical" in instructions -> Blocks
    payload = default_payload.copy()
    payload["task"] = {
        "title": "Clean desks",
        "instructions": "This is a medical note about cleaning.",
        "priority": "normal"
    }
    
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "This is a medical note."},
        transcript="Clean the desks.",
        payload=payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_policy_gate_local_path_blocks(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    # Local path C:\ in instructions -> Blocks
    payload = default_payload.copy()
    payload["task"] = {
        "title": "Clean desks",
        "instructions": "Log file at C:\\Users\\Administrator\\Desktop\\log.txt",
        "priority": "normal"
    }
    
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Log file path"},
        transcript="Clean the desks.",
        payload=payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_policy_gate_raw_transcript_leak_blocks(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    # Raw transcript is inside payload task instructions -> Blocks
    payload = default_payload.copy()
    payload["task"] = {
        "title": "Clean desks",
        "instructions": "Do research on fractional math. Raw text: secret transcript.",
        "priority": "normal"
    }
    
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Instructions"},
        transcript="secret transcript",
        payload=payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_policy_gate_domain_unauthorized_blocks(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    
    allowed, _ = gate.is_external_dispatch_allowed(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Clean them."},
        transcript="Clean desks.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://malicious-site.com/functions/submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert allowed is False

def test_assess_outbound_structured_result(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    assessment = gate.assess_outbound(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Clean desks."},
        transcript="Please clean desks.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert assessment.automatic_classification == "non_sensitive"
    assert assessment.risk_level == "low"
    assert assessment.safe_auto_allowed is True
    assert len(assessment.findings) == 0


def test_external_action_requires_confirmation_phrase(
    temp_vault: Path, default_payload: dict, default_config: dict
) -> None:
    payload = dict(default_payload)
    payload["task"] = {
        "title": "Send owner test email",
        "instructions": "Send a brief test email to the configured owner.",
        "priority": "normal",
    }

    assessment = PolicyGate().assess_outbound(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task=payload["task"],
        transcript="Please send a brief test message to me.",
        payload=payload,
        source_device_id="device-001",
        target_agent="openclaw",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit-task",
        vault_path=str(temp_vault),
        config=default_config,
    )

    assert assessment.safe_auto_allowed is False
    assert "external_action_confirmation_missing" in assessment.findings


def test_external_action_confirmation_phrase_allows_exact_action(
    temp_vault: Path, default_payload: dict, default_config: dict
) -> None:
    payload = dict(default_payload)
    payload["task"] = {
        "title": "Send owner test email",
        "instructions": (
            "Send a brief test email to the configured owner. CONFIRM ACTION."
        ),
        "priority": "normal",
    }

    assessment = PolicyGate().assess_outbound(
        category="agent_task",
        sensitivity="non_sensitive",
        safe_task=payload["task"],
        transcript=(
            "OpenClaw, send a brief test email to me and confirm action now."
        ),
        payload=payload,
        source_device_id="device-001",
        target_agent="openclaw",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit-task",
        vault_path=str(temp_vault),
        config=default_config,
    )

    assert assessment.safe_auto_allowed is True
    assert "external_action_confirmed" in assessment.checks_passed

def test_assess_outbound_high_risk_findings(temp_vault: Path, default_payload: dict, default_config: dict) -> None:
    gate = PolicyGate()
    assessment = gate.assess_outbound(
        category="agent_task",
        sensitivity="student_sensitive",
        safe_task={"title": "Clean desks", "instructions": "Clean desks."},
        transcript="Sam Jones is missing.",
        payload=default_payload,
        source_device_id="device-001",
        target_agent="hermes",
        endpoint_url="https://ref.supabase.co/functions/v1/cvn-submit",
        vault_path=str(temp_vault),
        config=default_config
    )
    assert assessment.risk_level == "high"
    assert assessment.safe_auto_allowed is False
    assert "sensitivity_student_sensitive" in assessment.findings
    assert "student_name_match" in assessment.findings
    assert len(assessment.suggested_redactions) > 0

