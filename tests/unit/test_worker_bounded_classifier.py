import json
from pathlib import Path
from unittest.mock import MagicMock

from app.transcription.worker import PipelineWorker


def test_worker_uses_one_bounded_classifier_and_records_stage_timings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wav_path = tmp_path / "capture.wav"
    wav_path.write_bytes(b"RIFF test")
    vault_path = tmp_path / "vault"

    settings = MagicMock()
    requested_keys: list[str] = []

    def get_setting(key: str, default=None):
        requested_keys.append(key)
        return {
            "whisper_bin_path": "whisper.exe",
            "whisper_model_path": "model.bin",
            "ollama_url": "http://localhost:11434",
            "fast_model": "qwen3.5:latest",
            "fallback_model": "phi4-mini:3.8b",
            "classification_total_budget_seconds": 18.0,
            "obsidian_vault_path": str(vault_path),
            "agents.enabled": False,
        }.get(key, default)

    settings.get.side_effect = get_setting
    settings.external_sharing_enabled.return_value = False

    async def transcribe(*_args, **_kwargs):
        return "Send the draft for review"

    monkeypatch.setattr(
        "app.transcription.worker.WhisperTranscriber.transcribe",
        transcribe,
    )

    classifier = MagicMock()
    classifier.classify.return_value = {
        "category": "agent_task",
        "sensitivity": "unknown",
        "confidence": 0.0,
        "requires_review": True,
        "telegram_allowed": False,
    }
    classifier_type = MagicMock(return_value=classifier)
    monkeypatch.setattr("app.transcription.worker.OllamaClassifier", classifier_type)

    monkeypatch.setattr(
        "app.transcription.worker.PolicyGate.is_telegram_allowed",
        lambda *_args, **_kwargs: True,
    )
    writer = MagicMock()
    writer.write_note.return_value = str(vault_path / "note.md")
    monkeypatch.setattr("app.transcription.worker.ObsidianWriter", MagicMock(return_value=writer))

    routing_service = MagicMock()
    monkeypatch.setattr(
        "app.destinations.outbound_routing_service.OutboundRoutingService",
        MagicMock(return_value=routing_service),
    )

    audit_events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.transcription.worker.log_audit_event",
        lambda event, _source, detail: audit_events.append((event, detail)),
    )

    PipelineWorker(str(wav_path), settings, 3.0).run()

    classifier_type.assert_called_once_with(
        "http://localhost:11434",
        "qwen3.5:latest",
        fallback_model="phi4-mini:3.8b",
        total_budget_seconds=18.0,
    )
    assert "careful_model" not in requested_keys
    routed_classification = routing_service.handle_capture.call_args.kwargs["classification"]
    assert routed_classification["route"] == "review_queue"
    assert routed_classification["telegram_allowed"] is False

    timing_detail = next(detail for event, detail in audit_events if event == "PIPELINE_TIMINGS")
    timings = json.loads(timing_detail)
    assert set(timings) == {
        "classification_seconds",
        "execution_timing",
        "pipeline_to_submission_seconds",
        "routing_seconds",
        "transcription_seconds",
    }
    assert timings["execution_timing"] == "remote_not_observed"
