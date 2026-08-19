from copy import deepcopy

from scripts.classification_benchmark import (
    FixtureBackend,
    format_report,
    load_cases,
    main,
    percentile_nearest_rank,
    run_benchmark,
    validate_result,
)


REQUIRED_KINDS = {
    "ordinary_note",
    "student_sensitive_observation",
    "reminder",
    "draft_email",
    "confirmed_send_email",
    "ollama_unavailable",
    "malformed_response",
    "noisy_classroom_audio",
}


def test_fixture_suite_covers_priority_regressions() -> None:
    cases = load_cases()

    assert {case["kind"] for case in cases} == REQUIRED_KINDS
    assert len({case["id"] for case in cases}) == len(cases)
    noisy = next(case for case in cases if case["kind"] == "noisy_classroom_audio")
    assert noisy["source"] == "prerecorded_audio_transcript_fixture"


def test_failure_fixtures_fail_closed() -> None:
    failure_kinds = {"ollama_unavailable", "malformed_response"}

    for case in load_cases():
        if case["kind"] in failure_kinds:
            result = case["scripted_result"]
            assert result["route"] == "review_queue"
            assert result["sensitivity"] == "unknown"
            assert result["telegram_allowed"] is False
            assert result["requires_review"] is True
            assert result["confidence"] == 0.0


def test_confirmed_email_preserves_exact_action_literals() -> None:
    case = next(case for case in load_cases() if case["kind"] == "confirmed_send_email")
    result = case["scripted_result"]

    assert result["category_fields"]["recipient"] == "me"
    assert result["category_fields"]["subject_line"] == "CVN action check 8B"
    assert result["task"]["instructions"] == (
        'Send an email to me with subject "CVN action check 8B" and body '
        '"The red folder is ready, please archive it."\n\nCONFIRM ACTION'
    )


def test_deterministic_benchmark_reports_p95_and_passes_threshold() -> None:
    report = run_benchmark(load_cases(), FixtureBackend(), repetitions=3)

    assert report.case_count == 8
    assert report.sample_count == 24
    assert report.p95_ms == 610.0
    assert report.p95_limit_ms == 15_000.0
    assert report.passed is True
    assert "not real Ollama performance" in format_report(report)


def test_benchmark_fails_when_p95_exceeds_configured_limit() -> None:
    report = run_benchmark(load_cases(), FixtureBackend(), p95_limit_ms=500.0)

    assert report.p95_ms == 610.0
    assert report.latency_passed is False
    assert report.passed is False


def test_validation_reports_dotted_path_mismatches() -> None:
    mismatches = validate_result(
        {"task": {"instructions": "Send it"}},
        {"task.instructions": "Draft it", "route": "email_draft"},
    )

    assert mismatches == (
        "task.instructions: value mismatch",
        "route: missing",
    )


def test_fixture_output_regression_is_reported_without_aborting() -> None:
    cases = deepcopy(load_cases())
    cases[0]["scripted_result"]["route"] = "telegram_agent_task"

    report = run_benchmark(cases, FixtureBackend())

    assert report.correctness_passed is False
    assert report.runs[0].mismatches == (
        "route: value mismatch",
    )


def test_timing_report_never_echoes_classification_content() -> None:
    cases = deepcopy(load_cases())
    action_case = next(case for case in cases if case["kind"] == "confirmed_send_email")
    action_case["scripted_result"]["task"]["instructions"] = "unsafe changed body"

    rendered = format_report(run_benchmark(cases, FixtureBackend()))

    assert "unsafe changed body" not in rendered
    assert "CVN action check 8B" not in rendered
    assert "The red folder is ready" not in rendered
    assert "task.instructions: value mismatch" in rendered


def test_nearest_rank_percentile_is_deterministic() -> None:
    assert percentile_nearest_rank([1, 2, 3, 4, 100], 50) == 3
    assert percentile_nearest_rank([1, 2, 3, 4, 100], 95) == 100


def test_cli_fixture_backend_never_needs_ollama(capsys) -> None:
    exit_code = main(["--backend", "fixture", "--max-p95-ms", "15000"])

    assert exit_code == 0
    assert "Classification benchmark: fixture" in capsys.readouterr().out
