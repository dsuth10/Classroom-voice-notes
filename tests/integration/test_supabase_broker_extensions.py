# tests/integration/test_supabase_broker_extensions.py
import os
import sys
import secrets
import datetime
import requests
import json
import hashlib
import hmac
import pytest

PROJECT_REF = "ukqkkgzimhtjhlnmlyao"
BASE_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1"

MISSING_ENV = False
def _get_env(name: str) -> str:
    global MISSING_ENV
    val = os.environ.get(name, "").strip()
    if not val:
        MISSING_ENV = True
    return val

CLIENT_BEARER = _get_env("CVN_BEARER_TOKEN")
CLIENT_HMAC   = _get_env("CVN_HMAC_SECRET")
WORKER_BEARER = _get_env("AGENT_BROKER_BEARER_TOKEN")
WORKER_HMAC   = _get_env("AGENT_BROKER_HMAC_SECRET")

def hmac_sha256_hex(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()

def make_signed_client_post(endpoint: str, payload: dict) -> requests.Response:
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac_sha256_hex(body_str, CLIENT_HMAC)
    return requests.post(
        f"{BASE_URL}/{endpoint}",
        data=body_str,
        headers={
            "Authorization": f"Bearer {CLIENT_BEARER}",
            "x-cvn-signature": sig,
            "Content-Type": "application/json"
        },
        timeout=30.0
    )

def make_signed_worker_post(endpoint: str, payload: dict, key_id: str = None, bearer: str = None, hmac_secret: str = None) -> requests.Response:
    use_bearer = bearer if bearer else WORKER_BEARER
    use_hmac = hmac_secret if hmac_secret else WORKER_HMAC
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac_sha256_hex(body_str, use_hmac)
    headers = {
        "Authorization": f"Bearer {use_bearer}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }
    if key_id:
        headers["x-cvn-key-id"] = key_id
    return requests.post(
        f"{BASE_URL}/{endpoint}",
        data=body_str,
        headers=headers,
        timeout=30.0
    )

def get_task_status(task_id: str) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    signed_at = now.isoformat()
    nonce = secrets.token_hex(16)
    canonical = f"GET\n/functions/v1/cvn-status/{task_id}\ntask_id={task_id}\nsigned_at={signed_at}\nnonce={nonce}"
    sig = hmac_sha256_hex(canonical, CLIENT_HMAC)

    res = requests.get(
        f"{BASE_URL}/cvn-status/{task_id}",
        params={
            "signed_at": signed_at,
            "nonce": nonce
        },
        headers={
            "Authorization": f"Bearer {CLIENT_BEARER}",
            "x-cvn-signature": sig
        },
        timeout=30.0
    )
    if res.status_code == 200:
        return res.json()
    raise RuntimeError(f"Failed to query status: {res.status_code} {res.text}")

@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_broker_extensions():
    print("\n[*] Starting Phase 2C.0 Broker Extensions Staging Tests...")

    # 1. Submit an 'openclaw' task
    now = datetime.datetime.now(datetime.timezone.utc)
    task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()
    submit_payload = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": task_id,
        "created_at": now.isoformat(),
        "source": "classroom_voice_notes",
        "source_device_id": "test-device-extensions",
        "target_agent": "openclaw",
        "privacy": {
            "classification": "non_sensitive",
            "policy_gate_version": "1.0.0",
            "checks_passed": ["category_agent_task"]
        },
        "task": {
            "title": "OpenClaw Staging Test",
            "instructions": '{"task_type": "cvn.test", "payload": {"test_mode": "success"}}'
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "idempotency_key": "key-" + secrets.token_hex(8)
    }

    print(f"[*] Submitting openclaw task {task_id}...")
    res = make_signed_client_post("cvn-submit-task", submit_payload)
    assert res.status_code == 200, f"Submit failed: {res.text}"

    # 2. Try to claim as a 'hermes' worker. It should NOT claim it.
    print("[*] Worker polling for hermes targets...")
    claim_payload = {
        "worker_id": "worker-hermes-01",
        "vt_seconds": 1800,
        "target_agent": "hermes",
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post("cvn-claim-task", claim_payload)
    assert res.status_code == 200
    data = res.json()
    if data["claimed"]:
        assert data["task_id"] != task_id, "Hermes worker claimed the OpenClaw task!"
        print("[+] Claimed another pending task, but successfully avoided claiming OpenClaw task.")
    else:
        print("[+] Verified: Hermes worker did not claim OpenClaw task.")

    # 3. Claim as an 'openclaw' worker. It should claim it.
    print("[*] Worker polling for openclaw targets...")
    claim_payload["target_agent"] = "openclaw"
    claim_payload["worker_id"] = "worker-openclaw-01"
    claim_payload["nonce"] = secrets.token_hex(16)
    res = make_signed_worker_post(
        "cvn-claim-task",
        claim_payload,
        key_id="test-openclaw-worker-01",
        bearer="fixture_openclaw_bearer_1234567890",
        hmac_secret="fixture_openclaw_hmac_secret_1234567890"
    )
    assert res.status_code == 200
    data = res.json()
    assert data["claimed"] is True
    assert data["task_id"] == task_id
    assert data["target_agent"] == "openclaw"
    print("[+] Verified: OpenClaw worker successfully claimed OpenClaw task.")

    # 4. Fail task with 'disposition: permanent'
    print("[*] Submitting permanent failure...")
    fail_payload = {
        "task_id": task_id,
        "worker_id": "worker-openclaw-01",
        "failure": {
            "code": "TEST_PERMANENT_ERROR",
            "message": "This is a test permanent failure.",
            "disposition": "permanent"
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post(
        "cvn-fail-task",
        fail_payload,
        key_id="test-openclaw-worker-01",
        bearer="fixture_openclaw_bearer_1234567890",
        hmac_secret="fixture_openclaw_hmac_secret_1234567890"
    )
    assert res.status_code == 200
    fail_res = res.json()
    assert fail_res["success"] is True
    assert fail_res["status"] == "dead_letter"
    print("[+] Verified: Permanent failure transition status: dead_letter.")

    # Verify status and error_code
    status_data = get_task_status(task_id)
    assert status_data["status"] == "dead_letter"
    assert status_data["error_code"] == "TEST_PERMANENT_ERROR"
    assert status_data["error_message"] == "This is a test permanent failure."
    print("[+] Verified: Status endpoint returned dead_letter and correct error_code/message.")

    # 5. Submit another task to test 'disposition: execution_unknown' (manual_review)
    task_id2 = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()
    submit_payload["task_id"] = task_id2
    submit_payload["idempotency_key"] = "key-" + secrets.token_hex(8)
    submit_payload["nonce"] = secrets.token_hex(16)

    print(f"[*] Submitting second task {task_id2}...")
    res = make_signed_client_post("cvn-submit-task", submit_payload)
    assert res.status_code == 200

    # Claim it
    claim_payload["nonce"] = secrets.token_hex(16)
    res = make_signed_worker_post(
        "cvn-claim-task",
        claim_payload,
        key_id="test-openclaw-worker-01",
        bearer="fixture_openclaw_bearer_1234567890",
        hmac_secret="fixture_openclaw_hmac_secret_1234567890"
    )
    assert res.status_code == 200
    assert res.json()["claimed"] is True

    # Fail with execution_unknown
    print("[*] Submitting execution_unknown failure...")
    fail_payload2 = {
        "task_id": task_id2,
        "worker_id": "worker-openclaw-01",
        "failure": {
            "code": "EXECUTION_TIMEOUT_UNKNOWN",
            "message": "Gateway read timeout occurred.",
            "disposition": "execution_unknown"
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post(
        "cvn-fail-task",
        fail_payload2,
        key_id="test-openclaw-worker-01",
        bearer="fixture_openclaw_bearer_1234567890",
        hmac_secret="fixture_openclaw_hmac_secret_1234567890"
    )
    assert res.status_code == 200
    fail_res2 = res.json()
    assert fail_res2["success"] is True
    assert fail_res2["status"] == "manual_review"
    print("[+] Verified: Execution unknown failure transitions status to manual_review.")

    # Verify status and error_code
    status_data2 = get_task_status(task_id2)
    assert status_data2["status"] == "manual_review"
    assert status_data2["error_code"] == "EXECUTION_TIMEOUT_UNKNOWN"
    print("[+] Verified: Status endpoint returned manual_review and correct error_code.")

    print("[+] ALL Phase 2C.0 Broker Extensions staging tests passed!")

if __name__ == "__main__":
    test_broker_extensions()
