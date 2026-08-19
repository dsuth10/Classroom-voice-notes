import json
from unittest.mock import MagicMock, patch

from app.ollama_router.classifier import OllamaClassifier


def _ollama_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"response": json.dumps(payload)}
    return response


@patch("app.ollama_router.classifier.httpx.post")
def test_action_request_preserves_structured_task(mock_post: MagicMock) -> None:
    mock_post.return_value = _ollama_response(
        {
            "route": "telegram_agent_task",
            "category": "agent_task",
            "sensitivity": "non_sensitive",
            "confidence": 0.99,
            "title": "Send owner test email",
            "summary": "Send a test email to the owner.",
            "agent_target": "openclaw",
            "task": {
                "title": "Send owner test email",
                "instructions": "Send an email to me with subject CVN audio test and body AUDIO_ACTION_OK.",
                "priority": "HIGH",
            },
        }
    )

    result = OllamaClassifier().classify(
        "OpenClaw, send an email to me with subject CVN audio test and body AUDIO_ACTION_OK."
    )

    assert result["category"] == "agent_task"
    assert result["task"] == {
        "title": "Send owner test email",
        "instructions": "Send an email to me with subject CVN audio test and body AUDIO_ACTION_OK.",
        "priority": "high",
    }
    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert '"send an email" is an agent_task' in prompt
    assert "self-contained task object" in prompt


@patch("app.ollama_router.classifier.httpx.post")
def test_agent_task_falls_back_to_safe_summary(mock_post: MagicMock) -> None:
    mock_post.return_value = _ollama_response(
        {
            "route": "telegram_agent_task",
            "category": "agent_task",
            "sensitivity": "non_sensitive",
            "confidence": 0.9,
            "title": "Research warm-ups",
            "summary": "Find three general fraction warm-up activities.",
            "agent_target": "openclaw",
        }
    )

    result = OllamaClassifier().classify("Find three general fraction warm-up activities.")

    assert result["task"] == {
        "title": "Research warm-ups",
        "instructions": "Find three general fraction warm-up activities.",
        "priority": "normal",
    }


@patch("app.ollama_router.classifier.httpx.post")
def test_non_agent_note_does_not_keep_task(mock_post: MagicMock) -> None:
    mock_post.return_value = _ollama_response(
        {
            "route": "email_draft",
            "category": "email_draft",
            "sensitivity": "non_sensitive",
            "confidence": 0.9,
            "title": "Draft newsletter",
            "summary": "Draft a newsletter email for review.",
            "task": {"instructions": "Send it now"},
        }
    )

    result = OllamaClassifier().classify("Draft a newsletter email for me to review.")

    assert result["task"] is None


@patch("app.ollama_router.classifier.httpx.post")
def test_email_action_repairs_owner_alias_and_standalone_confirmation(
    mock_post: MagicMock,
) -> None:
    mock_post.return_value = _ollama_response(
        {
            "route": "telegram_agent_task",
            "category": "agent_task",
            "sensitivity": "non_sensitive",
            "confidence": 0.98,
            "title": "Send Email to Teacher",
            "summary": "Send a test email.",
            "agent_target": "openclaw",
            "category_fields": {
                "recipient": "me",
                "subject_line": "CVN audio action test",
            },
            "task": {
                "title": "Send Email to Teacher",
                "instructions": (
                    "Send an email to the teacher with subject 'CVN audio action test' "
                    "and body 'audio action okay confirm action'."
                ),
                "priority": "normal",
            },
        }
    )

    result = OllamaClassifier().classify(
        "Hey Joshua OpenClaw send an email to me with subjects CVN audio action test "
        "and body audio action okay confirm action save"
    )

    assert result["task"]["instructions"] == (
        'Send an email to me with subject "CVN audio action test" '
        'and body "audio action okay"\n\nCONFIRM ACTION'
    )


@patch("app.ollama_router.classifier.httpx.post")
def test_email_action_preserves_arbitrary_recipient_fields(mock_post: MagicMock) -> None:
    original = "Send an email to the principal for review."
    mock_post.return_value = _ollama_response(
        {
            "route": "telegram_agent_task",
            "category": "agent_task",
            "sensitivity": "non_sensitive",
            "confidence": 0.98,
            "agent_target": "openclaw",
            "task": {"instructions": original},
        }
    )

    result = OllamaClassifier().classify(
        "OpenClaw send an email to the principal with subject Update and body Hello."
    )

    assert result["task"]["instructions"] == (
        'Send an email to the principal with subject "Update" and body "Hello."'
    )
