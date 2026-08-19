import json
from unittest.mock import MagicMock, patch

import httpx

from app.ollama_router.classifier import OllamaClassifier


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"response": json.dumps(payload)}
    return response


def _safe_task() -> dict:
    return {
        "route": "telegram_agent_task",
        "category": "agent_task",
        "sensitivity": "non_sensitive",
        "confidence": 0.96,
        "contains_student_information": False,
        "contains_external_task": True,
        "telegram_allowed": True,
        "requires_review": False,
        "title": "Research task",
        "summary": "Research fractions.",
        "task": {
            "title": "Research task",
            "instructions": "Research fractions.",
            "priority": "normal",
        },
    }


@patch("app.ollama_router.classifier.httpx.post")
def test_timeout_uses_one_smaller_fallback_under_shared_budget(mock_post: MagicMock) -> None:
    request = httpx.Request("POST", "http://localhost:11434/api/generate")
    mock_post.side_effect = [httpx.ReadTimeout("timed out", request=request), _response(_safe_task())]

    result = OllamaClassifier(
        model="qwen3.5:latest",
        fallback_model="phi4-mini:3.8b",
        total_budget_seconds=18.0,
    ).classify("Research fractions.")

    assert result["category"] == "agent_task"
    assert result["telegram_allowed"] is True
    assert mock_post.call_count == 2
    assert [call.kwargs["json"]["model"] for call in mock_post.call_args_list] == [
        "qwen3.5:latest",
        "phi4-mini:3.8b",
    ]
    assert mock_post.call_args_list[0].kwargs["timeout"] <= 13.5
    assert mock_post.call_args_list[1].kwargs["timeout"] <= 18.0


@patch("app.ollama_router.classifier.httpx.post")
def test_ollama_receives_pydantic_schema_and_non_thinking_options(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(_safe_task())

    OllamaClassifier().classify("Research fractions.")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["think"] is False
    assert payload["keep_alive"] == "10m"
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_predict"] == 512
    assert payload["format"]["title"] == "ClassificationResult"
    assert "properties" in payload["format"]
    assert set(payload["format"]["required"]) == set(payload["format"]["properties"])
    assert "default" not in json.dumps(payload["format"])


@patch("app.ollama_router.classifier.httpx.post")
def test_malformed_primary_and_fallback_fail_closed(mock_post: MagicMock) -> None:
    malformed = MagicMock()
    malformed.status_code = 200
    malformed.json.return_value = {"response": "not json"}
    mock_post.return_value = malformed

    result = OllamaClassifier().classify("Send something externally.")

    assert mock_post.call_count == 2
    assert result["category"] == "unknown"
    assert result["route"] == "review_queue"
    assert result["sensitivity"] == "unknown"
    assert result["requires_review"] is True
    assert result["telegram_allowed"] is False


@patch("app.ollama_router.classifier.httpx.post")
def test_uncertain_external_privacy_fails_closed_after_one_fallback(
    mock_post: MagicMock,
) -> None:
    uncertain = _safe_task()
    uncertain.pop("contains_student_information")
    mock_post.return_value = _response(uncertain)

    result = OllamaClassifier().classify("Send the task externally.")

    assert mock_post.call_count == 2
    assert result["category"] == "agent_task"
    assert result["route"] == "review_queue"
    assert result["sensitivity"] == "unknown"
    assert result["confidence"] == 0.0
    assert result["requires_review"] is True
    assert result["telegram_allowed"] is False


@patch("app.ollama_router.classifier.httpx.post")
def test_confirmation_is_never_invented(mock_post: MagicMock) -> None:
    payload = _safe_task()
    payload["task"]["instructions"] = "Research fractions. CONFIRM ACTION"
    mock_post.return_value = _response(payload)

    result = OllamaClassifier().classify("Research fractions.")

    assert result["task"]["instructions"] == "Research fractions."


@patch("app.ollama_router.classifier.httpx.post")
def test_iso_reminder_time_is_normalised_for_existing_writers(mock_post: MagicMock) -> None:
    payload = {
        "route": "local_reminder",
        "category": "reminder",
        "sensitivity": "teacher_private",
        "confidence": 0.98,
        "contains_student_information": False,
        "contains_external_task": False,
        "telegram_allowed": False,
        "requires_review": False,
        "title": "Print safety sheets",
        "summary": "Print the science safety sheets.",
        "reminder_time": "2026-08-20T07:45:00+10:00",
    }
    mock_post.return_value = _response(payload)

    result = OllamaClassifier().classify("Remind me to print the safety sheets.")

    assert result["reminder_time"] == "2026-08-20 07:45:00"


@patch("app.ollama_router.classifier.httpx.post")
def test_explicit_send_email_intent_repairs_model_category(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(
        {
            "route": "local_reminder",
            "category": "reminder",
            "sensitivity": "teacher_private",
            "confidence": 0.95,
            "contains_student_information": False,
            "title": "CVN action check 8B",
            "summary": "The red folder is ready.",
        }
    )

    result = OllamaClassifier().classify(
        "OpenClaw send an email to me with subject CVN action check 8B and body "
        "The red folder is ready, please archive it. CONFIRM ACTION"
    )

    assert result["category"] == "agent_task"
    assert result["sensitivity"] == "non_sensitive"
    assert result["telegram_allowed"] is True
    assert result["agent_target"] == "openclaw"
    assert result["category_fields"]["recipient"] == "me"
    assert result["category_fields"]["subject_line"] == "CVN action check 8B"
    assert result["task"]["instructions"] == (
        'Send an email to me with subject "CVN action check 8B" and body '
        '"The red folder is ready, please archive it."\n\nCONFIRM ACTION'
    )


@patch("app.ollama_router.classifier.httpx.post")
def test_email_action_with_student_signal_still_fails_closed(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(
        {
            "route": "local_obsidian",
            "category": "general_note",
            "sensitivity": "teacher_private",
            "confidence": 0.95,
            "contains_student_information": None,
            "title": "Email parent",
            "summary": "Contact a parent.",
        }
    )

    result = OllamaClassifier().classify(
        "Send an email to the parent with subject Student update and body "
        "The student needs support. CONFIRM ACTION"
    )

    assert result["route"] == "review_queue"
    assert result["sensitivity"] == "unknown"
    assert result["telegram_allowed"] is False
    assert result["requires_review"] is True


@patch("app.ollama_router.classifier.httpx.post")
def test_draft_email_do_not_send_is_not_promoted_to_action(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(
        {
            "route": "local_obsidian",
            "category": "general_note",
            "sensitivity": "student_sensitive",
            "confidence": 0.95,
            "contains_student_information": True,
            "title": "Excursion hats",
            "summary": "Email request.",
        }
    )

    result = OllamaClassifier().classify(
        "Draft an email to the Year 6 families with subject Excursion hats and "
        "body Please pack a broad-brimmed hat on Friday. Do not send it."
    )

    assert result["category"] == "email_draft"
    assert result["route"] == "email_draft"
    assert result["requires_review"] is True
    assert result["telegram_allowed"] is False
    assert result["category_fields"]["recipient"] == "the Year 6 families"
    assert result["category_fields"]["subject_line"] == "Excursion hats"
    assert result["summary"] == (
        "Draft an email to the Year 6 families with subject Excursion hats and "
        "body Please pack a broad-brimmed hat on Friday."
    )


@patch("app.ollama_router.classifier.httpx.post")
def test_year_level_cohort_is_not_an_identifiable_student(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(
        {
            "route": "local_student_note",
            "category": "general_note",
            "sensitivity": "student_sensitive",
            "confidence": 0.95,
            "contains_student_information": True,
            "title": "Year 6 class note",
            "summary": "The class settled quickly.",
            "category_fields": {"students_mentioned": ["Year 6 class"]},
        }
    )

    result = OllamaClassifier().classify(
        "The Year 6 class settled quickly after lunch and completed a fraction warm-up."
    )

    assert result["route"] == "local_obsidian"
    assert result["sensitivity"] == "teacher_private"
    assert result["contains_student_information"] is False
    assert result["category_fields"]["students_mentioned"] == []
