import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from app.destinations.telegram_dispatcher import TelegramDispatcher

def test_resolve_agent() -> None:
    """Verifies that TelegramDispatcher correctly resolves the target agent based on keywords, classifier suggestions, or default settings."""
    settings = MagicMock()
    settings.get.side_effect = lambda k: {
        "agents.default_agent": "hermes"
    }.get(k)
    
    dispatcher = TelegramDispatcher(settings)
    
    # 1. Keyword scans take absolute precedence
    assert dispatcher.resolve_agent("Please ask Hermes to do planning.", {"agent_target": "openclaw"}) == "hermes"
    assert dispatcher.resolve_agent("Tell OpenClaw to write code.", {"agent_target": "hermes"}) == "openclaw"
    assert dispatcher.resolve_agent("Tell open claw to parse this.", {}) == "openclaw"
    
    # 2. Classification suggestions fall back if no keywords present
    assert dispatcher.resolve_agent("Write a summary of the first fleet.", {"agent_target": "openclaw"}) == "openclaw"
    assert dispatcher.resolve_agent("Research fractional math methods.", {"agent_target": "hermes"}) == "hermes"
    
    # 3. Default setting fallback
    assert dispatcher.resolve_agent("Do something general.", {"agent_target": "auto"}) == "hermes"
    assert dispatcher.resolve_agent("Generic request.", {}) == "hermes"


def test_format_message() -> None:
    """Verifies message layout and parameter inclusion in formatted message."""
    dispatcher = TelegramDispatcher(MagicMock())
    message = dispatcher.format_message("CVN-12345", "Generate warmups.", "agent_task")
    
    assert "📋 *Agent Task* `[CVN-12345]`" in message
    assert "Generate warmups." in message
    assert "📂 *Category*: agent_task" in message


@patch("app.destinations.telegram_dispatcher.httpx.post")
def test_dispatch_success(mock_post: MagicMock, tmp_path: Path) -> None:
    """Verifies successful telegram dispatch and frontmatter update."""
    settings = MagicMock()
    settings.get.side_effect = lambda k: {
        "agents.telegram_token": "mock_token",
        "agents.agents.hermes.chat_id": "123456",
        "agents.default_agent": "hermes"
    }.get(k)
    
    dispatcher = TelegramDispatcher(settings)
    
    # Setup successful mock response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp
    
    # Setup dummy note file
    note_file = tmp_path / "agent_note.md"
    note_content = "---\ntype: classroom-voice-note\nstatus: captured\ncategory: agent_task\n---\nBody content"
    note_file.write_text(note_content, encoding="utf-8")
    
    # Run dispatch
    success = dispatcher.dispatch("Help with fractions", {"category": "agent_task", "agent_target": "hermes"}, str(note_file))
    
    assert success is True
    mock_post.assert_called_once()
    
    # Verify frontmatter was updated to sent
    updated_content = note_file.read_text(encoding="utf-8")
    assert "status: sent" in updated_content
    assert "agent_target: hermes" in updated_content
    assert "task_id: CVN-" in updated_content
    assert "sent_at: " in updated_content


@patch("app.destinations.telegram_dispatcher.httpx.post")
def test_dispatch_retry_and_failure(mock_post: MagicMock, tmp_path: Path) -> None:
    """Verifies retry and final failure handling of the dispatcher."""
    settings = MagicMock()
    settings.get.side_effect = lambda k: {
        "agents.telegram_token": "mock_token",
        "agents.agents.hermes.chat_id": "123456",
        "agents.default_agent": "hermes"
    }.get(k)
    
    dispatcher = TelegramDispatcher(settings)
    
    # Force failures (exceptions)
    mock_post.side_effect = Exception("Connection Timeout")
    
    # Setup dummy note file
    note_file = tmp_path / "failed_note.md"
    note_content = "---\ntype: classroom-voice-note\nstatus: captured\ncategory: agent_task\n---\nBody content"
    note_file.write_text(note_content, encoding="utf-8")
    
    # Mock sleep to run test quickly
    with patch("time.sleep") as mock_sleep:
        success = dispatcher.dispatch("Help with fractions", {"category": "agent_task", "agent_target": "hermes"}, str(note_file))
        
        assert success is False
        assert mock_post.call_count == 3  # Initial + 2 retries
        assert mock_sleep.call_count == 2
        
    # Verify frontmatter shows failed dispatch
    updated_content = note_file.read_text(encoding="utf-8")
    assert "status: dispatch_failed" in updated_content
