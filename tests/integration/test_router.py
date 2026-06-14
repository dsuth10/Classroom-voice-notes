import pytest
from unittest import mock
from app.ollama_router.classifier import OllamaClassifier
from app.ollama_router.policy_gate import PolicyGate

@pytest.fixture
def mock_httpx() -> mock.MagicMock:
    with mock.patch("httpx.post") as mock_post:
        yield mock_post

def test_classifier_calls_ollama(mock_httpx: mock.MagicMock) -> None:
    """Verifies that OllamaClassifier calls the local Ollama server and parses JSON responses."""
    # Mock response from Ollama API
    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": '{"category": "behaviour_note", "sensitivity": "student_sensitive", "confidence": 0.95}'
    }
    mock_httpx.return_value = mock_response
    
    classifier = OllamaClassifier(url="http://localhost:11434", model="qwen3.5:latest")
    result = classifier.classify("Alex threw a paper airplane.")
    
    mock_httpx.assert_called_once()
    assert result["category"] == "behaviour_note"
    assert result["sensitivity"] == "student_sensitive"
    assert result["confidence"] == 0.95

def test_policy_gate_blocks_sensitive_routing() -> None:
    """Verifies that the policy gate overrides routing to block external Telegram messages for sensitive data."""
    gate = PolicyGate()
    
    # Sensitive case: student_sensitive
    assert not gate.is_telegram_allowed("student_sensitive", "behaviour_note", "Alex threw a paper airplane.")
    
    # Sensitive case: teacher_private
    assert not gate.is_telegram_allowed("teacher_private", "general_note", "Alex was absent.")
    
    # Non-sensitive case: general planning
    assert gate.is_telegram_allowed("non_sensitive", "agent_task", "Find fraction misconceptions.")
