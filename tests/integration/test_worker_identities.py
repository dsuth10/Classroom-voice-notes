# tests/integration/test_worker_identities.py
import os
import sys
import secrets
import datetime
import requests
import json
import hashlib
import hmac
import pytest

# For local testing, use the local Supabase URL
LOCAL_URL = "http://127.0.0.1:54321/functions/v1"
BASE_URL = os.environ.get("CVN_TEST_BASE_URL", LOCAL_URL)

MISSING_ENV = False
def _get_env(name: str) -> str:
    global MISSING_ENV
    val = os.environ.get(name, "").strip()
    if not val:
        MISSING_ENV = True
    return val

CLIENT_BEARER = _get_env("CVN_BEARER_TOKEN")
CLIENT_HMAC   = _get_env("CVN_HMAC_SECRET")

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

def make_signed_worker_post(endpoint: str, payload: dict, key_id: str, bearer: str, hmac_secret: str) -> requests.Response:
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac_sha256_hex(body_str, hmac_secret)
    headers = {
        "Authorization": f"Bearer {bearer}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }
    if key_id:
        headers["x-cvn-key-id"] = key_id

    return requests.post(
        f"{BASE_URL}/{endpoint}",
        data=body_str,
        headers={k: str(v) for k, v in headers.items()},
        timeout=30.0
    )

def make_signed_client_status_get(task_id: str) -> requests.Response:
    now = datetime.datetime.now(datetime.timezone.utc)
    signed_at = now.isoformat()
    nonce = secrets.token_hex(16)
    canonical = f"GET\n/functions/v1/cvn-status/{task_id}\ntask_id={task_id}\nsigned_at={signed_at}\nnonce={nonce}"
    sig = hmac_sha256_hex(canonical, CLIENT_HMAC)
    return requests.get(
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

def make_signed_worker_status_get(task_id: str, key_id: str, bearer: str, hmac_secret: str) -> requests.Response:
    now = datetime.datetime.now(datetime.timezone.utc)
    signed_at = now.isoformat()
    nonce = secrets.token_hex(16)
    canonical = f"GET\n/functions/v1/cvn-status/{task_id}\ntask_id={task_id}\nsigned_at={signed_at}\nnonce={nonce}"
    sig = hmac_sha256_hex(canonical, hmac_secret)
    headers = {
        "Authorization": f"Bearer {bearer}",
        "x-cvn-signature": sig
    }
    if key_id:
        headers["x-cvn-key-id"] = key_id

    return requests.get(
        f"{BASE_URL}/cvn-status/{task_id}",
        params={
            "signed_at": signed_at,
            "nonce": nonce
        },
        headers={k: str(v) for k, v in headers.items()},
        timeout=30.0
    )

@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_worker_identities():
    print("\n[*] Starting Phase 2C.1 Worker Identity Authentication Tests...")

    # Staging keys
    HERMES_KEY_ID = "test-hermes-worker-01"
    HERMES_BEARER = "fixture_hermes_bearer_1234567890"
    HERMES_HMAC = "fixture_hermes_hmac_secret_1234567890"

    OC_KEY_ID = "test-openclaw-worker-01"
    OC_BEARER = "fixture_openclaw_bearer_1234567890"
    OC_HMAC = "fixture_openclaw_hmac_secret_1234567890"

    EMPTY_KEY_ID = "test-empty-allowlist-worker"
    EMPTY_BEARER = "fixture_empty_bearer_1234567890"
    EMPTY_HMAC = "fixture_empty_hmac_secret_1234567890"

    MISSING_KEY_ID = "test-missing-allowlist-worker"
    MISSING_BEARER = "fixture_missing_bearer_1234567890"
    MISSING_HMAC = "fixture_missing_hmac_secret_1234567890"

    # --- 1. Submission of tasks ---
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1.1 Hermes task
    hermes_task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-HERM"
    submit_hermes = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": hermes_task_id,
        "created_at": now.isoformat(),
        "source": "classroom_voice_notes",
        "source_device_id": "test-device",
        "target_agent": "hermes",
        "privacy": {
            "classification": "non_sensitive",
            "policy_gate_version": "1.0.0",
            "checks_passed": ["category_agent_task"]
        },
        "task": {
            "title": "Hermes Auth Test Task",
            "instructions": '{"task_type": "cvn.test"}'
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "idempotency_key": "idemp-herm-" + secrets.token_hex(8)
    }

    res = make_signed_client_post("cvn-submit-task", submit_hermes)
    assert res.status_code == 200, f"Hermes task submit failed: {res.text}"
    print("[+] Hermes task submitted successfully")

    # 1.2 OpenClaw task
    oc_task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-OCLW"
    submit_oc = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": oc_task_id,
        "created_at": now.isoformat(),
        "source": "classroom_voice_notes",
        "source_device_id": "test-device",
        "target_agent": "openclaw",
        "privacy": {
            "classification": "non_sensitive",
            "policy_gate_version": "1.0.0",
            "checks_passed": ["category_agent_task"]
        },
        "task": {
            "title": "OpenClaw Auth Test Task",
            "instructions": '{"task_type": "cvn.test"}'
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "idempotency_key": "idemp-oc-" + secrets.token_hex(8)
    }

    res = make_signed_client_post("cvn-submit-task", submit_oc)
    assert res.status_code == 200, f"OpenClaw task submit failed: {res.text}"
    print("[+] OpenClaw task submitted successfully")

    # --- 2. Worker ID Authorisation checks ---

    # 2.1 Correct key, target and worker ID (should succeed)
    claim_payload = {
        "worker_id": "hermes-test-worker",
        "target_agent": "hermes",
        "vt_seconds": 60,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post("cvn-claim-task", claim_payload, HERMES_KEY_ID, HERMES_BEARER, HERMES_HMAC)
    assert res.status_code == 200, f"Expected 200 for correct claim, got: {res.status_code} {res.text}"
    print("[+] Correct key, target, and worker ID succeeded (200)")

    # 2.2 Correct key and target but incorrect worker ID (should return 403)
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    claim_payload["worker_id"] = "incorrect-worker-id"
    res = make_signed_worker_post("cvn-claim-task", claim_payload, HERMES_KEY_ID, HERMES_BEARER, HERMES_HMAC)
    assert res.status_code == 403, f"Expected 403 for incorrect worker ID, got: {res.status_code} {res.text}"
    print("[+] Correct key/target but incorrect worker ID was rejected (403)")

    # 2.3 Empty worker-ID allowlist (should fail with 401 or 403)
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    claim_payload["worker_id"] = "hermes-test-worker"
    res = make_signed_worker_post("cvn-claim-task", claim_payload, EMPTY_KEY_ID, EMPTY_BEARER, EMPTY_HMAC)
    assert res.status_code in (401, 403), f"Expected 401/403 for empty worker-ID allowlist, got: {res.status_code} {res.text}"
    print("[+] Empty worker-ID allowlist failed as expected")

    # 2.4 Missing worker-ID allowlist (should fail with 401 or 403)
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    res = make_signed_worker_post("cvn-claim-task", claim_payload, MISSING_KEY_ID, MISSING_BEARER, MISSING_HMAC)
    assert res.status_code in (401, 403), f"Expected 401/403 for missing worker-ID allowlist, got: {res.status_code} {res.text}"
    print("[+] Missing worker-ID allowlist failed as expected")

    # 2.5 VPS credential impersonating the Windows worker (should return 403)
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    claim_payload["target_agent"] = "openclaw"
    claim_payload["worker_id"] = "hermes-test-worker"
    res = make_signed_worker_post("cvn-claim-task", claim_payload, OC_KEY_ID, OC_BEARER, OC_HMAC)
    assert res.status_code == 403, f"Expected 403 for VPS impersonating Windows, got: {res.status_code} {res.text}"
    print("[+] VPS credential impersonating Windows worker was rejected (403)")

    # 2.6 Windows credential impersonating the VPS worker (should return 403)
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    claim_payload["target_agent"] = "hermes"
    claim_payload["worker_id"] = "openclaw-test-worker"
    res = make_signed_worker_post("cvn-claim-task", claim_payload, HERMES_KEY_ID, HERMES_BEARER, HERMES_HMAC)
    assert res.status_code == 403, f"Expected 403 for Windows impersonating VPS, got: {res.status_code} {res.text}"
    print("[+] Windows credential impersonating VPS worker was rejected (403)")

    # --- 3. cvn-status Authorisation checks ---

    # 3.1 OpenClaw worker can view an OpenClaw task (should succeed)
    res = make_signed_worker_status_get(oc_task_id, OC_KEY_ID, OC_BEARER, OC_HMAC)
    assert res.status_code == 200, f"Expected 200 for OpenClaw worker status request, got: {res.status_code} {res.text}"
    task_data = res.json()
    assert task_data["task_id"] == oc_task_id
    print("[+] OpenClaw worker successfully viewed OpenClaw task")

    # 3.2 OpenClaw worker cannot view a Hermes task (should return 403)
    res = make_signed_worker_status_get(hermes_task_id, OC_KEY_ID, OC_BEARER, OC_HMAC)
    assert res.status_code == 403, f"Expected 403 for OpenClaw worker viewing Hermes task, got: {res.status_code} {res.text}"
    print("[+] OpenClaw worker blocked from viewing Hermes task (403)")

    # 3.3 Hermes/Windows worker cannot view an OpenClaw task (should return 403)
    res = make_signed_worker_status_get(oc_task_id, HERMES_KEY_ID, HERMES_BEARER, HERMES_HMAC)
    assert res.status_code == 403, f"Expected 403 for Hermes worker viewing OpenClaw task, got: {res.status_code} {res.text}"
    print("[+] Hermes worker blocked from viewing OpenClaw task (403)")

    # 3.4 Client status access continues to work (should succeed)
    res = make_signed_client_status_get(hermes_task_id)
    assert res.status_code == 200, f"Expected 200 for Client status on Hermes task, got: {res.status_code} {res.text}"
    res = make_signed_client_status_get(oc_task_id)
    assert res.status_code == 200, f"Expected 200 for Client status on OpenClaw task, got: {res.status_code} {res.text}"
    print("[+] Client status access works on both tasks")

    # 3.5 Neither status path exposes payloads, claim tokens or secrets
    for response_body in [
        make_signed_worker_status_get(oc_task_id, OC_KEY_ID, OC_BEARER, OC_HMAC).json(),
        make_signed_client_status_get(oc_task_id).json()
    ]:
        assert "payload" not in response_body, "Status leaked task payload!"
        assert "payload_json" not in response_body, "Status leaked task payload_json!"
        assert "claim_token" not in response_body, "Status leaked claim token!"
        assert "claimed_by" not in response_body, "Status leaked claimed_by!"
        assert "queue_msg_id" not in response_body, "Status leaked queue message ID!"
    print("[+] Verified: No status path exposes payloads, claim tokens, or secrets")

    print("[*] All Worker Identity and cvn-status Tests Passed!")

def submit_test_task_for_worker(suffix: str, target_agent: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + suffix.upper()
    payload = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": task_id,
        "created_at": now.isoformat(),
        "source": "classroom_voice_notes",
        "source_device_id": "test-device",
        "target_agent": target_agent,
        "privacy": {
            "classification": "non_sensitive",
            "policy_gate_version": "1.0.0",
            "checks_passed": ["category_agent_task"]
        },
        "task": {
            "title": f"Staging Auth Test Task {task_id}",
            "instructions": '{"task_type": "cvn.test"}'
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "idempotency_key": "idemp-rot-" + secrets.token_hex(8)
    }
    res = make_signed_client_post("cvn-submit-task", payload)
    assert res.status_code == 200, f"Task submit failed: {res.text}"
    return task_id

@pytest.mark.skipif(MISSING_ENV, reason="Missing environment variables for staging tests")
def test_credential_disable_rotation():
    print("\n[*] Starting Phase 2C.1 Credential Disable & Rotation Tests...")

    # We only run this test if targeting staging
    if "ukqkkgzimhtjhlnmlyao" not in BASE_URL:
        print("[*] Skipping staging-only rotation tests (not targeting staging URL)")
        return

    # Define standard keys registry (we must preserve these so other tests can pass)
    base_registry = {
        "version": "1.0",
        "keys": {
            "test-hermes-worker-01": {
                "enabled": True,
                "bearer_token": "fixture_hermes_bearer_1234567890",
                "hmac_secret": "fixture_hermes_hmac_secret_1234567890",
                "allowed_targets": ["hermes"],
                "allowed_worker_ids": ["hermes-test-worker", "worker-hermes-01"]
            },
            "test-openclaw-worker-01": {
                "enabled": True,
                "bearer_token": "fixture_openclaw_bearer_1234567890",
                "hmac_secret": "fixture_openclaw_hmac_secret_1234567890",
                "allowed_targets": ["openclaw"],
                "allowed_worker_ids": ["openclaw-test-worker", "worker-openclaw-01"]
            },
            "test-empty-allowlist-worker": {
                "enabled": True,
                "bearer_token": "fixture_empty_bearer_1234567890",
                "hmac_secret": "fixture_empty_hmac_secret_1234567890",
                "allowed_targets": ["hermes"],
                "allowed_worker_ids": []
            },
            "test-missing-allowlist-worker": {
                "enabled": True,
                "bearer_token": "fixture_missing_bearer_1234567890",
                "hmac_secret": "fixture_missing_hmac_secret_1234567890",
                "allowed_targets": ["hermes"]
            }
        }
    }

    # Dynamic retrieval of staging VPS credentials to preserve them in base_registry
    vps_bearer = None
    vps_hmac = None
    try:
        import subprocess
        vps_bearer = subprocess.run(['ssh', 'contabo-vault', 'sudo systemd-creds decrypt /etc/cvn/credentials/cvn-broker-bearer'], capture_output=True, text=True).stdout.strip()
        vps_hmac = subprocess.run(['ssh', 'contabo-vault', 'sudo systemd-creds decrypt /etc/cvn/credentials/cvn-broker-hmac'], capture_output=True, text=True).stdout.strip()
        if vps_bearer and vps_hmac and not vps_bearer.startswith("ssh") and not vps_hmac.startswith("ssh"):
            base_registry["keys"]["vps-worker-staging"] = {
                "enabled": True,
                "bearer_token": vps_bearer,
                "hmac_secret": vps_hmac,
                "allowed_targets": ["openclaw"],
                "allowed_worker_ids": ["vps-worker-id-staging"]
            }
            print("[+] Successfully retrieved and merged vps-worker-staging credentials into base_registry")
        else:
            print("[-] Decrypted credentials from VPS were empty or invalid.")
    except Exception as e:
        print(f"[-] Warning: Failed to retrieve vps-worker-staging credentials from VPS: {e}")

    import copy
    import time

    def push_registry(registry_dict: dict):
        registry_json = json.dumps(registry_dict)
        cmd = [
            "npx", "supabase", "secrets", "set",
            f"AGENT_BROKER_WORKER_CREDENTIALS={registry_json}",
            "--project-ref", "ukqkkgzimhtjhlnmlyao"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if res.returncode != 0:
            err = res.stderr.replace(registry_json, "[REDACTED]")
            out = res.stdout.replace(registry_json, "[REDACTED]")
            raise RuntimeError(f"Failed to set staging secrets: {err}\n{out}")
        # Wait 15 seconds for Supabase to propagate secrets to functions
        time.sleep(15)

    # 1. Generate fresh staging-only credentials
    ROT_KEY_ID = "test-rotation-worker-01"
    bearer_1 = "rot_bearer_" + secrets.token_hex(16)
    hmac_1 = "rot_hmac_" + secrets.token_hex(16)

    # 2. Setup registry with enabled key
    registry = copy.deepcopy(base_registry)
    registry["keys"][ROT_KEY_ID] = {
        "enabled": True,
        "bearer_token": bearer_1,
        "hmac_secret": hmac_1,
        "allowed_targets": ["hermes"],
        "allowed_worker_ids": ["rotation-test-worker"]
    }

    print("[*] Test 1: Setting up enabled credential...")
    push_registry(registry)

    # Verify enabled credential succeeds
    task_id_1 = submit_test_task_for_worker("rot1", "hermes")

    claim_payload = {
        "worker_id": "rotation-test-worker",
        "target_agent": "hermes",
        "vt_seconds": 60,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post("cvn-claim-task", claim_payload, ROT_KEY_ID, bearer_1, hmac_1)
    assert res.status_code == 200, f"Expected 200 for enabled credential, got {res.status_code} {res.text}"
    print("[+] Enabled credential succeeds (200)")

    # 3. Disable the credential
    print("[*] Test 2: Disabling credential...")
    registry["keys"][ROT_KEY_ID]["enabled"] = False
    push_registry(registry)

    # Verify disabled credential returns 401
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    res = make_signed_worker_post("cvn-claim-task", claim_payload, ROT_KEY_ID, bearer_1, hmac_1)
    assert res.status_code == 401, f"Expected 401 for disabled credential, got {res.status_code} {res.text}"
    print("[+] Disabled credential returns 401")

    # 4. Rotate credential
    print("[*] Test 3: Rotating credential...")
    bearer_2 = "rot_bearer_" + secrets.token_hex(16)
    hmac_2 = "rot_hmac_" + secrets.token_hex(16)
    registry["keys"][ROT_KEY_ID]["enabled"] = True
    registry["keys"][ROT_KEY_ID]["bearer_token"] = bearer_2
    registry["keys"][ROT_KEY_ID]["hmac_secret"] = hmac_2
    push_registry(registry)

    # Verify old credential fails
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    res = make_signed_worker_post("cvn-claim-task", claim_payload, ROT_KEY_ID, bearer_1, hmac_1)
    assert res.status_code == 401, f"Expected 401 for old credential, got {res.status_code} {res.text}"
    print("[+] Old credential fails after rotation (401)")

    # Verify new credential succeeds
    task_id_2 = submit_test_task_for_worker("rot2", "hermes")
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    res = make_signed_worker_post("cvn-claim-task", claim_payload, ROT_KEY_ID, bearer_2, hmac_2)
    assert res.status_code == 200, f"Expected 200 for new credential, got {res.status_code} {res.text}"
    print("[+] New credential succeeds after rotation (200)")

    # 5. Restore/Re-enable credential
    print("[*] Test 4: Disabling then restoring/re-enabling credential...")
    registry["keys"][ROT_KEY_ID]["enabled"] = False
    push_registry(registry)

    # Verify disabled returns 401
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    res = make_signed_worker_post("cvn-claim-task", claim_payload, ROT_KEY_ID, bearer_2, hmac_2)
    assert res.status_code == 401

    # Re-enable
    registry["keys"][ROT_KEY_ID]["enabled"] = True
    push_registry(registry)

    # Verify restored succeeds
    task_id_3 = submit_test_task_for_worker("rot3", "hermes")
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    res = make_signed_worker_post("cvn-claim-task", claim_payload, ROT_KEY_ID, bearer_2, hmac_2)
    assert res.status_code == 200, f"Expected 200 for re-enabled credential, got {res.status_code} {res.text}"
    print("[+] Restored/re-enabled credential behaves as expected (200)")

    # 6. Final Clean up: Restore base registry
    print("[*] Test 5: Restoring baseline registry...")
    push_registry(base_registry)
    print("[+] Staging registry restored to baseline.")

    # 7. Post-restoration verification of permanent credential
    print("[*] Test 6: Verifying permanent credential after cleanup...")
    task_id_perm = submit_test_task_for_worker("perm", "hermes")
    claim_payload_perm = {
        "worker_id": "hermes-test-worker",
        "target_agent": "hermes",
        "vt_seconds": 60,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post(
        "cvn-claim-task",
        claim_payload_perm,
        key_id="test-hermes-worker-01",
        bearer="fixture_hermes_bearer_1234567890",
        hmac_secret="fixture_hermes_hmac_secret_1234567890"
    )
    assert res.status_code == 200, f"Expected 200 for restored permanent credential, got {res.status_code} {res.text}"
    print("[+] Verified restored permanent credential completes a successful authenticated request (200)")

    # 8. Post-restoration verification that rotated credentials return 401
    print("[*] Test 7: Verifying rotated credentials fail after cleanup...")
    claim_payload_rot_fail = {
        "worker_id": "rotation-test-worker",
        "target_agent": "hermes",
        "vt_seconds": 60,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16)
    }
    res = make_signed_worker_post(
        "cvn-claim-task",
        claim_payload_rot_fail,
        key_id=ROT_KEY_ID,
        bearer=bearer_2,
        hmac_secret=hmac_2
    )
    assert res.status_code == 401, f"Expected 401 for rotated credential after cleanup, got {res.status_code} {res.text}"
    print("[+] Verified rotated credential returns 401 after cleanup")

    # 9. Post-restoration verification that permanent VPS staging worker credential succeeds
    if vps_bearer and vps_hmac:
        print("[*] Test 8: Verifying permanent VPS staging credential after cleanup...")
        task_id_vps = submit_test_task_for_worker("VPST", "openclaw")
        claim_payload_vps = {
            "worker_id": "vps-worker-id-staging",
            "target_agent": "openclaw",
            "vt_seconds": 60,
            "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "nonce": secrets.token_hex(16)
        }
        res = make_signed_worker_post(
            "cvn-claim-task",
            claim_payload_vps,
            key_id="vps-worker-staging",
            bearer=vps_bearer,
            hmac_secret=vps_hmac
        )
        assert res.status_code == 200, f"Expected 200 for restored VPS credential, got {res.status_code} {res.text}"
        print("[+] Verified restored permanent VPS staging credential completes a successful authenticated request (200)")

    print("[*] All Disable and Rotation Tests Passed!")

if __name__ == "__main__":
    test_worker_identities()
    test_credential_disable_rotation()
