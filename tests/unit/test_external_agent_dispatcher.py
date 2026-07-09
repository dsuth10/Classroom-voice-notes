import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import httpx
from app.destinations.external_agent_dispatcher import ExternalAgentDispatcher
from app.destinations.external_outbox import ExternalOutbox

@pytest.fixture
def mock_settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.get.side_effect = lambda k: {
        "external_agent.enabled": True,
        "external_agent.endpoint_url": "https://ref.supabase.co/functions/v1/cvn-submit",
        "external_agent.hmac_secret_ref": "cvn_hmac_secret",
        "external_agent.bearer_token_ref": "cvn_bearer_token",
        "external_agent.target_agent_default": "hermes",
        "external_agent.source_device_id": "test-device-001",
        "external_agent.allowed_target_agents": ["hermes", "openclaw", "auto"],
        "external_agent.allowed_endpoint_domains": ["supabase.co"],
        "obsidian_vault_path": str(tmp_path / "ObsidianVault")
    }.get(k)
    return settings

@pytest.fixture
def mock_outbox(tmp_path: Path) -> ExternalOutbox:
    db_file = tmp_path / "test_dispatcher_outbox.db"
    return ExternalOutbox(db_file)

@patch("app.config.keyring_store.get_secret")
@patch("app.ollama_router.policy_gate.PolicyGate.is_external_dispatch_allowed")
@patch("app.destinations.external_agent_dispatcher.httpx.post")
def test_dispatcher_dispatch_success(
    mock_post: MagicMock,
    mock_policy: MagicMock,
    mock_keyring: MagicMock,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
    tmp_path: Path
) -> None:
    # Setup mocks
    mock_keyring.side_effect = lambda ref: "mock_secret_val" if ref in ("cvn_hmac_secret", "cvn_bearer_token") else None
    mock_policy.return_value = (True, ["check1", "check2"])
    
    # Setup network success
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"msg_id": "remote-msg-123", "accepted": True}
    mock_post.return_value = mock_response
    
    # Setup dummy note file
    note_file = tmp_path / "note1.md"
    note_file.write_text("---\nstatus: captured\n---\nBody text", encoding="utf-8")
    
    classification = {
        "title": "Clean desks",
        "summary": "Ensure desks are clean.",
        "category": "agent_task",
        "sensitivity": "non_sensitive"
    }
    
    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)
    success = dispatcher.dispatch(classification, str(note_file), "Clean desks transcript")
    
    assert success is True
    assert mock_post.call_count == 1
    
    # Check outbox is marked sent
    stats = mock_outbox.get_stats()
    assert stats["sent"] == 1
    
    # Check frontmatter was updated to sent
    note_content = note_file.read_text(encoding="utf-8")
    assert "status: sent" in note_content
    assert "agent_target: hermes" in note_content

@patch("app.config.keyring_store.get_secret")
def test_dispatcher_dispatch_disabled(
    mock_keyring: MagicMock,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
    tmp_path: Path
) -> None:
    mock_settings.get.side_effect = lambda k: {
        "external_agent.enabled": False
    }.get(k)
    
    note_file = tmp_path / "note2.md"
    note_file.write_text("---\nstatus: captured\n---\nBody text", encoding="utf-8")
    
    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)
    success = dispatcher.dispatch({}, str(note_file), "")
    
    assert success is False
    assert mock_keyring.call_count == 0

@patch("app.config.keyring_store.get_secret")
@patch("app.ollama_router.policy_gate.PolicyGate.is_external_dispatch_allowed")
@patch("app.destinations.external_agent_dispatcher.httpx.post")
def test_dispatcher_dispatch_network_failure(
    mock_post: MagicMock,
    mock_policy: MagicMock,
    mock_keyring: MagicMock,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
    tmp_path: Path
) -> None:
    # Setup mocks
    mock_keyring.side_effect = lambda ref: "mock_secret_val" if ref in ("cvn_hmac_secret", "cvn_bearer_token") else None
    mock_policy.return_value = (True, ["check1", "check2"])
    
    # Network throws error
    mock_post.side_effect = httpx.RequestError("Connection timeout")
    
    # Setup dummy note file
    note_file = tmp_path / "note3.md"
    note_file.write_text("---\nstatus: captured\n---\nBody text", encoding="utf-8")
    
    classification = {
        "title": "Clean desks",
        "summary": "Ensure desks are clean.",
        "category": "agent_task",
        "sensitivity": "non_sensitive"
    }
    
    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)
    success = dispatcher.dispatch(classification, str(note_file), "Clean desks transcript")
    
    # Dispatch fails, but task is enqueued in outbox for retry
    assert success is False
    stats = mock_outbox.get_stats()
    assert stats["pending"] == 1
    
    note_content = note_file.read_text(encoding="utf-8")
    assert "status: dispatch_failed" in note_content
