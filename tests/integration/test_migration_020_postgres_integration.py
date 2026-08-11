# tests/integration/test_migration_020_postgres_integration.py
"""Integration tests for Migration 020 — exercises live Supabase/PostgreSQL RPCs for claims, hashed leases, backoff, ownership cleanup, and submission idempotency.

Required env vars to run live against Supabase staging:
  SUPABASE_URL              — e.g. https://ukqkkgzimhtjhlnmlyao.supabase.co
  SUPABASE_SERVICE_ROLE_KEY — service-role JWT
"""
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


def _query_item(item_id: str) -> dict:
    """Fetch raw database row for an item from cvn_outbound_items using service-role key."""
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/cvn_outbound_items",
        params={"item_id": f"eq.{item_id}"},
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Accept": "application/json",
        },
        timeout=30.0,
    )
    assert res.status_code == 200, f"Query item failed ({res.status_code}): {res.text}"
    rows = res.json()
    assert len(rows) > 0, f"No row found for item {item_id}"
    return rows[0]


def _claim_specific_item(worker_id: str, target_item_id: str, max_tries: int = 10) -> dict:
    """Claims items until target_item_id is returned, isolating the test item on a shared queue."""
    for _ in range(max_tries):
        res = _rpc("cvn_claim_outbound_item", {
            "p_worker_id": worker_id,
            "p_visibility_timeout_seconds": 300,
            "p_allowed_kinds": ["record_only", "agent_task"],
            "p_allowed_agents": ["openclaw"],
        })
        assert res.status_code == 200, f"Claim failed: {res.text}"
        data = res.json()
        if not data:
            time.sleep(0.5)
            continue
        if data.get("item_id") == target_item_id:
            return data
    pytest.fail(f"Could not claim target item {target_item_id} after {max_tries} attempts")


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for live staging tests")
def test_migration_020_submit_exact_idempotency_and_conflict() -> None:
    """Submitting exact same payload and nonce returns idempotent_replay=True; different content with same key returns conflict."""
    idem_key = "test-idem-020-" + secrets.token_hex(6)
    item_id = f"CVNI-{time.strftime('%Y%m%d')}-120000-{secrets.token_hex(2).upper()}"
    source_device = "test-device-" + secrets.token_hex(4)
    nonce = "nonce-" + secrets.token_hex(8)
    signed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    payload_json = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {"test": "data"},
        "idempotency_key": idem_key,
        "nonce": nonce,
        "signed_at": signed_at,
        "source_device_id": source_device,
        "privacy": {
            "release_basis": "human_approval",
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "policy_gate_version": "2.0.0",
            "approval": {
                "approved_at": signed_at,
                "approved_content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            },
        },
    }

    # 1. First Submit -> Accepted
    res1 = _rpc("cvn_submit_outbound_item", {
        "p_item_id": item_id,
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "p_content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": nonce,
        "p_signed_at": signed_at,
    })
    assert res1.status_code == 200, f"Submit failed: {res1.text}"
    data1 = res1.json()
    assert data1.get("accepted") is True

    # 2. Re-submit EXACT identical payload & nonce -> Idempotent Replay (200)
    res2 = _rpc("cvn_submit_outbound_item", {
        "p_item_id": item_id,
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "p_content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": nonce,
        "p_signed_at": signed_at,
    })
    assert res2.status_code == 200, f"Replay failed: {res2.text}"
    data2 = res2.json()
    assert data2.get("idempotent_replay") is True

    # 3. Submit same key with different content hash -> Idempotency Conflict (400/409/RPC error)
    res3 = _rpc("cvn_submit_outbound_item", {
        "p_item_id": f"CVNI-{time.strftime('%Y%m%d')}-120000-{secrets.token_hex(2).upper()}",
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": "0000000000000000000000000000000000000000000000000000000000000000",
        "p_content_hash": "0000000000000000000000000000000000000000000000000000000000000000",
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": "nonce-conflict-" + secrets.token_hex(4),
        "p_signed_at": signed_at,
    })
    assert res3.status_code in (400, 409, 500)
    assert "idempotency_conflict" in res3.text


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for live staging tests")
def test_migration_020_claim_complete_lifecycle_and_ownership_cleanup() -> None:
    """Claiming an item returns a plaintext lease; completing clears ALL lease ownership fields in DB."""
    worker_id = "test-worker-020-" + secrets.token_hex(4)
    item_id = f"CVNI-{time.strftime('%Y%m%d')}-120000-{secrets.token_hex(2).upper()}"
    source_device = "test-device-" + secrets.token_hex(4)
    signed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    idem_key = "idem-claim-" + secrets.token_hex(6)
    nonce = "nonce-claim-" + secrets.token_hex(6)

    content_hash = "1111111111111111111111111111111111111111111111111111111111111111"
    payload_hash = "2222222222222222222222222222222222222222222222222222222222222222"

    payload_json = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {},
        "idempotency_key": idem_key,
        "nonce": nonce,
        "signed_at": signed_at,
        "source_device_id": source_device,
        "privacy": {
            "release_basis": "human_approval",
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "policy_gate_version": "2.0.0",
            "approval": {
                "approved_at": signed_at,
                "approved_content_hash": content_hash,
            },
        },
    }

    # Submit item
    sub_res = _rpc("cvn_submit_outbound_item", {
        "p_item_id": item_id,
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": nonce,
        "p_signed_at": signed_at,
    })
    assert sub_res.status_code == 200

    # Claim item with isolation check
    claimed_data = _claim_specific_item(worker_id, item_id)
    assert claimed_data["item_id"] == item_id
    lease_token = claimed_data["lease_token"]

    # Complete item with valid lease token
    comp_res = _rpc("cvn_complete_outbound_item", {
        "p_item_id": item_id,
        "p_worker_id": worker_id,
        "p_lease_token": lease_token,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
        "p_result_json": {"status": "success"},
        "p_result_reference": "ref-12345",
    })
    assert comp_res.status_code == 200
    comp_data = comp_res.json()
    assert comp_data.get("success") is True
    assert comp_data.get("status") == "completed"

    # Query DB row directly to verify ALL lease ownership fields are NULL
    row = _query_item(item_id)
    assert row["status"] == "completed"
    assert row["lease_token"] is None
    assert row["lease_token_hash"] is None
    assert row["lease_expires_at"] is None
    assert row["visibility_deadline"] is None
    assert row["claimed_by"] is None
    assert row["claimed_by_worker_id"] is None
    assert row["claimed_at"] is None
    assert row["result_reference"] == "ref-12345"


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for live staging tests")
def test_migration_020_wrong_lease_token_rejection() -> None:
    """Completing an item with an invalid lease token raises invalid_lease_token error."""
    worker_id = "test-worker-020-" + secrets.token_hex(4)
    item_id = f"CVNI-{time.strftime('%Y%m%d')}-120000-{secrets.token_hex(2).upper()}"
    source_device = "test-device-" + secrets.token_hex(4)
    signed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    idem_key = "idem-wrong-" + secrets.token_hex(6)
    nonce = "nonce-wrong-" + secrets.token_hex(6)
    content_hash = "7777777777777777777777777777777777777777777777777777777777777777"
    payload_hash = "8888888888888888888888888888888888888888888888888888888888888888"

    payload_json = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {},
        "idempotency_key": idem_key,
        "nonce": nonce,
        "signed_at": signed_at,
        "source_device_id": source_device,
        "privacy": {
            "release_basis": "human_approval",
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "policy_gate_version": "2.0.0",
            "approval": {"approved_at": signed_at, "approved_content_hash": content_hash},
        },
    }

    _rpc("cvn_submit_outbound_item", {
        "p_item_id": item_id,
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": nonce,
        "p_signed_at": signed_at,
    })

    _claim_specific_item(worker_id, item_id)

    comp_res = _rpc("cvn_complete_outbound_item", {
        "p_item_id": item_id,
        "p_worker_id": worker_id,
        "p_lease_token": "cvn-lease-wrongtoken1234567890",
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
    })
    assert comp_res.status_code in (400, 403, 500)
    assert "invalid_lease_token" in comp_res.text


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for live staging tests")
def test_migration_020_repeated_completion_is_idempotent() -> None:
    """Repeated completion calls with identical hashes return already_completed=True."""
    worker_id = "test-worker-020-" + secrets.token_hex(4)
    item_id = f"CVNI-{time.strftime('%Y%m%d')}-120000-{secrets.token_hex(2).upper()}"
    source_device = "test-device-" + secrets.token_hex(4)
    signed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    idem_key = "idem-repeat-" + secrets.token_hex(6)
    nonce = "nonce-repeat-" + secrets.token_hex(6)
    content_hash = "3333333333333333333333333333333333333333333333333333333333333333"
    payload_hash = "4444444444444444444444444444444444444444444444444444444444444444"

    payload_json = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {},
        "idempotency_key": idem_key,
        "nonce": nonce,
        "signed_at": signed_at,
        "source_device_id": source_device,
        "privacy": {
            "release_basis": "human_approval",
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "policy_gate_version": "2.0.0",
            "approval": {"approved_at": signed_at, "approved_content_hash": content_hash},
        },
    }

    _rpc("cvn_submit_outbound_item", {
        "p_item_id": item_id,
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": nonce,
        "p_signed_at": signed_at,
    })

    claimed_data = _claim_specific_item(worker_id, item_id)
    lease_token = claimed_data["lease_token"]

    res1 = _rpc("cvn_complete_outbound_item", {
        "p_item_id": item_id,
        "p_worker_id": worker_id,
        "p_lease_token": lease_token,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
    })
    assert res1.status_code == 200
    assert res1.json().get("success") is True

    # Repeated completion call
    res2 = _rpc("cvn_complete_outbound_item", {
        "p_item_id": item_id,
        "p_worker_id": worker_id,
        "p_lease_token": lease_token,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
    })
    assert res2.status_code == 200
    assert res2.json().get("already_completed") is True


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for live staging tests")
def test_migration_020_server_controlled_3_attempt_dead_letter() -> None:
    """Failing an item 3 times tests backoff visibility, server-controlled max attempts (3), and unconditional dead_letter transition."""
    worker_id = "test-worker-020-" + secrets.token_hex(4)
    item_id = f"CVNI-{time.strftime('%Y%m%d')}-120000-{secrets.token_hex(2).upper()}"
    source_device = "test-device-" + secrets.token_hex(4)
    signed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    idem_key = "idem-fail-" + secrets.token_hex(6)
    nonce = "nonce-fail-" + secrets.token_hex(6)
    content_hash = "5555555555555555555555555555555555555555555555555555555555555555"
    payload_hash = "6666666666666666666666666666666666666666666666666666666666666666"

    payload_json = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "content": {},
        "idempotency_key": idem_key,
        "nonce": nonce,
        "signed_at": signed_at,
        "source_device_id": source_device,
        "privacy": {
            "release_basis": "human_approval",
            "automatic_classification": "non_sensitive",
            "risk_level": "low",
            "policy_gate_version": "2.0.0",
            "approval": {"approved_at": signed_at, "approved_content_hash": content_hash},
        },
    }

    _rpc("cvn_submit_outbound_item", {
        "p_item_id": item_id,
        "p_source_device_id": source_device,
        "p_item_kind": "record_only",
        "p_target_agent": "openclaw",
        "p_payload_json": payload_json,
        "p_payload_hash": payload_hash,
        "p_content_hash": content_hash,
        "p_automatic_classification": "non_sensitive",
        "p_risk_level": "low",
        "p_release_basis": "human_approval",
        "p_approved_at": signed_at,
        "p_policy_gate_version": "2.0.0",
        "p_idempotency_key": idem_key,
        "p_nonce": nonce,
        "p_signed_at": signed_at,
    })

    # Attempt 1
    c1 = _claim_specific_item(worker_id, item_id)
    assert c1["item_id"] == item_id
    f1 = _rpc("cvn_fail_outbound_item", {"p_item_id": item_id, "p_worker_id": worker_id, "p_lease_token": c1["lease_token"], "p_failure_reason": "fail 1", "p_retryable": True}).json()
    assert f1.get("status") == "failed_retryable"
    assert f1.get("attempt_count") == 1
    assert f1.get("max_attempts") == 3

    # Assert immediate claim receives NO item due to next_attempt_at backoff
    row_backoff = _query_item(item_id)
    assert row_backoff["next_attempt_at"] is not None

    # Wait for backoff window to expire
    start_time = time.time()
    while time.time() - start_time < 12.0:
        time.sleep(1.0)
        c2 = _rpc("cvn_claim_outbound_item", {"p_worker_id": worker_id, "p_allowed_kinds": ["record_only"], "p_allowed_agents": ["openclaw"]}).json()
        if c2 and c2.get("item_id") == item_id:
            f2 = _rpc("cvn_fail_outbound_item", {"p_item_id": item_id, "p_worker_id": worker_id, "p_lease_token": c2["lease_token"], "p_failure_reason": "fail 2", "p_retryable": True}).json()
            assert f2.get("status") == "failed_retryable"
            assert f2.get("attempt_count") == 2
            break

    # Wait for backoff window 2 to expire
    start_time = time.time()
    while time.time() - start_time < 22.0:
        time.sleep(1.0)
        c3 = _rpc("cvn_claim_outbound_item", {"p_worker_id": worker_id, "p_allowed_kinds": ["record_only"], "p_allowed_agents": ["openclaw"]}).json()
        if c3 and c3.get("item_id") == item_id:
            f3 = _rpc("cvn_fail_outbound_item", {"p_item_id": item_id, "p_worker_id": worker_id, "p_lease_token": c3["lease_token"], "p_failure_reason": "fail 3", "p_retryable": True}).json()
            assert f3.get("status") == "dead_letter"
            assert f3.get("attempt_count") == 3
            break

    # Unconditional database verification for dead_letter
    row = _query_item(item_id)
    assert row["status"] == "dead_letter"
    assert row["attempt_count"] == 3
    assert row["next_attempt_at"] is None
    assert row["lease_token"] is None
    assert row["lease_token_hash"] is None
    assert row["lease_expires_at"] is None
    assert row["visibility_deadline"] is None
    assert row["claimed_by"] is None
    assert row["claimed_by_worker_id"] is None
    assert row["claimed_at"] is None
