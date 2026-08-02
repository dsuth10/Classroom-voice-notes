"""Unit tests for PR 3: schema-aware endpoint routing.

V1 tasks must always reach cvn-submit-task.
V2 items must always reach cvn-submit-outbound-item.
Unknown schemas fail closed.
"""
import os
import pytest
from unittest import mock

from app.config.environment import (
    UnsupportedContractVersion,
    submission_endpoint,
    validate_broker_endpoint,
)

STAGING_BASE = "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1"
PROD_BASE = "https://slvzyasosjiteimonzen.supabase.co/functions/v1"


@pytest.fixture(autouse=True)
def set_staging_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVN_BROKER_ENV", "staging")


def test_v1_schema_routes_to_submit_task() -> None:
    url = submission_endpoint("cvn.agent_task.v1")
    assert url == f"{STAGING_BASE}/cvn-submit-task"


def test_v2_schema_routes_to_submit_outbound_item() -> None:
    url = submission_endpoint("cvn.outbound_item.v2")
    assert url == f"{STAGING_BASE}/cvn-submit-outbound-item"


def test_unknown_schema_raises_unsupported_contract_version() -> None:
    with pytest.raises(UnsupportedContractVersion, match="has no registered endpoint"):
        submission_endpoint("cvn.unknown_schema.v99")


def test_staging_endpoint_cannot_be_production_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging env cannot post to production host."""
    prod_url = f"{PROD_BASE}/cvn-submit-outbound-item"
    with pytest.raises(RuntimeError, match="approved staging Supabase functions host"):
        validate_broker_endpoint(prod_url)


def test_production_endpoint_cannot_be_staging_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production env cannot post to staging host."""
    monkeypatch.setenv("CVN_BROKER_ENV", "production")
    staging_url = f"{STAGING_BASE}/cvn-submit-task"
    with pytest.raises(RuntimeError, match="approved production Supabase functions host"):
        validate_broker_endpoint(staging_url)


def test_non_https_endpoint_rejected() -> None:
    http_url = "http://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-task"
    with pytest.raises(RuntimeError):
        validate_broker_endpoint(http_url)


def test_arbitrary_host_rejected() -> None:
    malicious_url = "https://evil.example.com/functions/v1/cvn-submit-task"
    with pytest.raises(RuntimeError):
        validate_broker_endpoint(malicious_url)


def test_query_string_rejected() -> None:
    url_with_query = f"{STAGING_BASE}/cvn-submit-task?token=bad"
    with pytest.raises(RuntimeError):
        validate_broker_endpoint(url_with_query)
