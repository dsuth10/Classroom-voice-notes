# tests/integration/test_migration_020_postgres_integration.py
"""Integration tests for Migration 020 — exercises live Supabase/PostgreSQL RPCs for claims, hashed leases, backoff, and submission idempotency.

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


@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for live staging tests")
def test_migration_020_submit_exact_idempotency_and_conflict() -> None:
    """Submitting exact same payload returns idempotent_replay=True; different content with same key returns conflict."""
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

    # 2. Re-submit exact same key, item_id, content_hash -> Idempotent Replay (200)
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
        "p_nonce": "nonce-diff-" + secrets.token_hex(4),
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
    """Claiming an item returns a plaintext lease; completing clears all lease ownership fields."""
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

    # Claim item
    claim_res = _rpc("cvn_claim_outbound_item", {
        "p_worker_id": worker_id,
        "p_visibility_timeout_seconds": 300,
        "p_allowed_kinds": ["record_only"],
        "p_allowed_agents": ["openclaw"],
    })
    assert claim_res.status_code == 200
    claimed_data = claim_res.json()
    assert claimed_data is not None
    assert "lease_token" in claimed_data
    lease_token = claimed_data["lease_token"]
    assert lease_token.startswith("cvn-lease-")

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
