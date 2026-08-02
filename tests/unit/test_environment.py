import pytest

from app.config.environment import get_broker_env, validate_broker_endpoint


def test_broker_environment_requires_exact_value(monkeypatch: pytest.MonkeyPatch) -> None:
    for invalid_value in ("", "Staging", "staging ", " production", "prod"):
        monkeypatch.setenv("CVN_BROKER_ENV", invalid_value)
        with pytest.raises(RuntimeError):
            get_broker_env()


def test_broker_endpoint_matches_active_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")
    validate_broker_endpoint(
        "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-task"
    )

    monkeypatch.setenv("CVN_BROKER_ENV", "production")
    validate_broker_endpoint(
        "https://slvzyasosjiteimonzen.supabase.co/functions/v1/cvn-submit-task"
    )


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-task",
        "https://ukqkkgzimhtjhlnmlyao.supabase.co.evil.example/functions/v1/cvn-submit-task",
        "https://ukqkkgzimhtjhlnmlyao.supabase.co@evil.example/functions/v1/cvn-submit-task",
        "https://ukqkkgzimhtjhlnmlyao.supabase.co:8443/functions/v1/cvn-submit-task",
        "https://ukqkkgzimhtjhlnmlyao.supabase.co/rest/v1/tasks",
        "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-task?redirect=1",
        "https://slvzyasosjiteimonzen.supabase.co/functions/v1/cvn-submit-task",
    ],
)
def test_broker_endpoint_rejects_unapproved_urls(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_url: str,
) -> None:
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")
    with pytest.raises(RuntimeError):
        validate_broker_endpoint(endpoint_url)
