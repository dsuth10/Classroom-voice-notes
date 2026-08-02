import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
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
        "external_agent.endpoint_url": "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-task",
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

@patch.dict(os.environ, {"CVN_BROKER_ENV": "staging"})
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
    mock_keyring.side_effect = lambda ref: "mock_secret_val" if "cvn_broker_hmac_secret" in ref or "cvn_broker_bearer_token" in ref or ref in ("cvn_hmac_secret", "cvn_bearer_token") else None
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
    unfinished = mock_outbox.get_unfinished_tasks()
    assert unfinished[0]["target_agent"] == "hermes"
    
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

@patch.dict(os.environ, {"CVN_BROKER_ENV": "staging"})
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
    mock_keyring.side_effect = lambda ref: "mock_secret_val" if "cvn_broker_hmac_secret" in ref or "cvn_broker_bearer_token" in ref or ref in ("cvn_hmac_secret", "cvn_bearer_token") else None
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


@patch.dict(os.environ, {"CVN_BROKER_ENV": "staging"})
@patch("app.config.keyring_store.get_secret")
@patch("app.destinations.external_agent_dispatcher.httpx.post")
def test_retry_pending_generates_fresh_request_nonces_per_attempt(
    mock_post: MagicMock,
    mock_keyring: MagicMock,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
) -> None:
    mock_keyring.side_effect = lambda ref: "mock_secret_val" if "cvn_broker_hmac_secret" in ref or "cvn_broker_bearer_token" in ref or ref in ("cvn_hmac_secret", "cvn_bearer_token") else None

    payload_nonce = "payload-nonce-12345678"
    mock_outbox.enqueue(
        task_id="CVN-RETRY-NONCE-TEST",
        endpoint_url="https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-outbound-item",
        payload_json=json.dumps({"task_id": "CVN-RETRY-NONCE-TEST", "nonce": payload_nonce}),
        payload_hash="hash",
        idempotency_key="idem-retry-nonce",
        nonce=payload_nonce,
        schema_version="cvn.outbound_item.v2",
    )

    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)
    
    # Attempt 1 (HTTP failure)
    mock_post.return_value = MagicMock(status_code=500, text="Internal Error")
    dispatcher.retry_pending()
    
    # Reset next_retry_at so it is eligible again immediately
    import sqlite3
    with sqlite3.connect(mock_outbox.db_path) as conn:
        conn.execute("UPDATE outbox SET status = 'pending', next_retry_at = CURRENT_TIMESTAMP")
    
    # Attempt 2
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"msg_id": "MSG-99"})
    dispatcher.retry_pending()

    assert mock_post.call_count == 2
    
    headers_attempt_1 = mock_post.call_args_list[0].kwargs["headers"]
    headers_attempt_2 = mock_post.call_args_list[1].kwargs["headers"]

    request_nonce_1 = headers_attempt_1["X-CVN-Nonce"]
    request_nonce_2 = headers_attempt_2["X-CVN-Nonce"]

    # Each attempt must have a fresh request nonce, separate from the payload nonce
    assert request_nonce_1 != request_nonce_2
    assert request_nonce_1 != payload_nonce
    assert request_nonce_2 != payload_nonce


@patch.dict(os.environ, {"CVN_BROKER_ENV": "staging"})
@patch("app.config.keyring_store.get_secret")
@patch("app.destinations.external_agent_dispatcher.httpx.post")
def test_retry_pending_rejects_unapproved_endpoint(
    mock_post: MagicMock,
    mock_keyring: MagicMock,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
) -> None:
    mock_outbox.enqueue(
        task_id="CVN-BAD-ENDPOINT",
        endpoint_url=(
            "https://ukqkkgzimhtjhlnmlyao.supabase.co.evil.example/"
            "functions/v1/cvn-submit-task"
        ),
        payload_json="{}",
        payload_hash="hash",
        idempotency_key="idem-bad-endpoint",
        nonce="nonce-bad-endpoint",
        schema_version="cvn.agent_task.v1",
    )

    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)
    assert dispatcher.retry_pending() == 0
    assert mock_outbox.get_stats()["dead_letter"] == 1
    mock_post.assert_not_called()
    mock_keyring.assert_not_called()


@patch.dict(os.environ, {"CVN_BROKER_ENV": "staging"})
@patch("app.config.keyring_store.get_secret")
def test_retry_pending_applies_retention_before_transmission(
    mock_keyring: MagicMock,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
) -> None:
    local_id = mock_outbox.enqueue(
        task_id="CVN-EXPIRED",
        endpoint_url=(
            "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/"
            "cvn-submit-task"
        ),
        payload_json="{}",
        payload_hash="hash",
        idempotency_key="idem-expired",
        nonce="nonce-expired",
        schema_version="cvn.agent_task.v1",
    )
    eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with sqlite3.connect(mock_outbox.db_path) as conn:
        conn.execute(
            "UPDATE outbox SET created_at = ? WHERE local_id = ?",
            (eight_days_ago, local_id),
        )
        conn.commit()

    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)
    assert dispatcher.retry_pending() == 0
    assert mock_outbox.get_stats()["dead_letter"] == 1
    mock_keyring.assert_not_called()


@pytest.mark.parametrize(
    ("target_agent", "persist_target"),
    [("hermes", True), ("openclaw", False)],
)
def test_reconcile_status_preserves_authoritative_target_agent(
    target_agent: str,
    persist_target: bool,
    mock_settings: MagicMock,
    mock_outbox: ExternalOutbox,
    tmp_path: Path,
) -> None:
    note_file = tmp_path / f"{target_agent}-task.md"
    note_file.write_text("---\nstatus: sent\n---\nTask note", encoding="utf-8")
    payload_json = json.dumps({"target_agent": target_agent})
    local_id = mock_outbox.enqueue(
        task_id=f"CVN-{target_agent.upper()}",
        endpoint_url=(
            "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/"
            "cvn-submit-task"
        ),
        payload_json=payload_json,
        payload_hash="hash",
        idempotency_key=f"idem-{target_agent}",
        nonce=f"nonce-{target_agent}",
        schema_version="cvn.agent_task.v1",
        note_path=str(note_file),
        target_agent=target_agent if persist_target else None,
    )

    mock_outbox.mark_sent(local_id, "remote-id")
    dispatcher = ExternalAgentDispatcher(mock_settings, mock_outbox)

    with patch.object(
        dispatcher,
        "check_task_status",
        return_value={
            "status": "completed",
            "completed_at": "2026-07-25T12:00:00+10:00",
            "result_summary": "Synthetic result",
        },
    ):
        assert dispatcher.reconcile_statuses() == 1

    note_content = note_file.read_text(encoding="utf-8")
    assert f"- **Agent:** {target_agent.capitalize()}" in note_content
    assert "status: completed" in note_content
    assert "Synthetic result" in note_content
    assert mock_outbox.get_stats()["completed"] == 1
