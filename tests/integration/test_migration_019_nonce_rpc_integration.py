# tests/integration/test_migration_019_nonce_rpc_integration.py
# Integration test for Migration 019 — exercises the LIVE cvn_register_request_nonce
# RPC function deployed to the staging Supabase project via the PostgREST /rpc endpoint.
#
# Required env vars:
#   SUPABASE_URL              — e.g. https://ukqkkgzimhtjhlnmlyao.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY — service-role JWT (NOT the anon key)
import os
import secrets
import time
import pytest
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

MISSING_ENV = not SUPABASE_URL or not SERVICE_KEY


def _rpc(rpc_name: str, params: dict) -> requests.Response:
    """Call a Supabase PostgREST RPC with the service-role key."""
    return requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/{rpc_name}",
        json=params,
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        timeout=30.0,
    )


def _register(
    credential_type: str = "worker",
    key_id: str | None = None,
    nonce: str | None = None,
    timestamp: int | None = None,
    ttl_seconds: int = 300,
) -> bool:
    if key_id is None:
        key_id = "test-migration-key-01"
    if nonce is None:
        nonce = secrets.token_hex(16)
    if timestamp is None:
        timestamp = int(time.time())
    res = _rpc(
        "cvn_register_request_nonce",
        {
            "p_credential_type": credential_type,
            "p_key_id": key_id,
            "p_nonce": nonce,
            "p_timestamp": timestamp,
            "p_ttl_seconds": ttl_seconds,
        },
    )
    assert res.status_code == 200, f"RPC failed ({res.status_code}): {res.text}"
    return res.json()


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_first_call_returns_true() -> None:
    """First registration of a fresh nonce must return true."""
    nonce = secrets.token_hex(16)
    result = _register(nonce=nonce)
    assert result is True, f"Expected True for fresh nonce, got {result!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_replay_returns_false() -> None:
    """Second registration of the same nonce (replay) must return false."""
    nonce = secrets.token_hex(16)
    key_id = "test-migration-replay-" + secrets.token_hex(4)
    ts = int(time.time())

    first = _register(key_id=key_id, nonce=nonce, timestamp=ts)
    assert first is True, f"Expected True for first call, got {first!r}"

    second = _register(key_id=key_id, nonce=nonce, timestamp=ts)
    assert second is False, f"Expected False (replay), got {second!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_invalid_credential_type_returns_false() -> None:
    """An invalid credential_type must be rejected (False)."""
    result = _register(credential_type="admin")
    assert result is False, f"Expected False for invalid credential_type, got {result!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_expired_timestamp_returns_false() -> None:
    """A timestamp outside the TTL window must be rejected (False)."""
    # Use a timestamp 10 minutes in the past with a 300 s TTL
    stale_ts = int(time.time()) - 610
    result = _register(timestamp=stale_ts, ttl_seconds=300)
    assert result is False, f"Expected False for expired timestamp, got {result!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_future_timestamp_returns_false() -> None:
    """A timestamp far in the future (clock-skew attack) must be rejected (False)."""
    future_ts = int(time.time()) + 610
    result = _register(timestamp=future_ts, ttl_seconds=300)
    assert result is False, f"Expected False for future timestamp, got {result!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_invalid_key_id_returns_false() -> None:
    """A key_id containing invalid characters must be rejected (False)."""
    result = _register(key_id="bad key; DROP TABLE--")
    assert result is False, f"Expected False for invalid key_id, got {result!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_short_nonce_returns_false() -> None:
    """A nonce shorter than 8 characters must be rejected (False)."""
    result = _register(nonce="short")
    assert result is False, f"Expected False for short nonce, got {result!r}"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_nonce_rpc_client_type_accepted() -> None:
    """credential_type='client' must also be accepted and replay-protected."""
    nonce = secrets.token_hex(16)
    key_id = "test-migration-client-" + secrets.token_hex(4)
    ts = int(time.time())

    first = _register(credential_type="client", key_id=key_id, nonce=nonce, timestamp=ts)
    assert first is True

    second = _register(credential_type="client", key_id=key_id, nonce=nonce, timestamp=ts)
    assert second is False


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_019_anon_key_is_denied_access() -> None:
    """Anonymous callers must not be able to invoke the RPC (permission check)."""
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not anon_key:
        pytest.skip("SUPABASE_ANON_KEY not set; skipping permission boundary test")

    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/cvn_register_request_nonce",
        json={
            "p_credential_type": "worker",
            "p_key_id": "test-anon",
            "p_nonce": secrets.token_hex(16),
            "p_timestamp": int(time.time()),
            "p_ttl_seconds": 300,
        },
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    assert res.status_code in (401, 403), (
        f"Expected 401/403 for anon caller, got {res.status_code}: {res.text}"
    )


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_migration_022_anon_key_is_denied_direct_nonce_table_access() -> None:
    """Anonymous callers must not be able to read the internal nonce table."""
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not anon_key:
        pytest.skip("SUPABASE_ANON_KEY not set; skipping permission boundary test")

    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/cvn_request_nonces?select=credential_type&limit=1",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
        },
        timeout=30.0,
    )
    assert res.status_code in (401, 403), (
        f"Expected 401/403 for direct anon table access, got "
        f"{res.status_code}: {res.text}"
    )
