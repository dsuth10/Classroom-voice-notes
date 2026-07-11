# tests/integration/test_worker_identities.py
import os
import sys
import secrets
import datetime
import requests
import json
import hashlib
import hmac
import time

# For local testing, use the local Supabase URL
# For staging, we would use the staging URL, but tests with fixture credentials
# should run against the local emulator to avoid leaking credentials to staging.
LOCAL_URL = "http://127.0.0.1:54321/functions/v1"
BASE_URL = os.environ.get("CVN_TEST_BASE_URL", LOCAL_URL)

def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"[-] Missing required environment variable: {name}")
        sys.exit(1)
    return val

CLIENT_BEARER = _require_env("CVN_BEARER_TOKEN")
CLIENT_HMAC   = _require_env("CVN_HMAC_SECRET")

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
        headers=headers,
        timeout=30.0
    )

def test_worker_identities():
    print("\n[*] Starting Phase 2C.1 Worker Identity Authentication Tests...")
    
    # We expect these fixture credentials to be configured in the local Supabase instance
    # via .env or secrets for testing.
    # Key 1: allowed for hermes
    HERMES_KEY_ID = "test-hermes-worker-01"
    HERMES_BEARER = "fixture_hermes_bearer_1234567890"
    HERMES_HMAC = "fixture_hermes_hmac_secret_1234567890"
    
    # Key 2: allowed for openclaw
    OC_KEY_ID = "test-openclaw-worker-01"
    OC_BEARER = "fixture_openclaw_bearer_1234567890"
    OC_HMAC = "fixture_openclaw_hmac_secret_1234567890"
    
    # 1. Submit a 'hermes' task
    now = datetime.datetime.now(datetime.timezone.utc)
    task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()
    submit_payload = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": task_id,
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
            "title": "Hermes Auth Test",
            "instructions": '{"task_type": "cvn.test"}'
        }
    }
    
    res = make_signed_client_post("cvn-submit-task", submit_payload)
    if res.status_code != 200:
        print(f"[-] Client submit failed: {res.status_code} {res.text}")
        sys.exit(1)
        
    print("[+] Client task submitted successfully")
    
    # 2. Try claiming hermes task with openclaw credentials (should fail)
    claim_payload = {
        "worker_id": "openclaw-test-worker",
        "target_agent": "hermes",
        "vt_seconds": 60,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16)
    }
    
    res = make_signed_worker_post("cvn-claim-task", claim_payload, OC_KEY_ID, OC_BEARER, OC_HMAC)
    if res.status_code != 403:
        print(f"[-] Expected 403 Forbidden for target mismatch, got: {res.status_code} {res.text}")
        sys.exit(1)
    
    print("[+] Correctly rejected claim from wrong target identity (403)")
    
    # 3. Try claiming with correct hermes credentials (should succeed)
    claim_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_payload["worker_id"] = "hermes-test-worker" # matching allowed_worker_ids logic if restricted
    
    res = make_signed_worker_post("cvn-claim-task", claim_payload, HERMES_KEY_ID, HERMES_BEARER, HERMES_HMAC)
    if res.status_code != 200:
        print(f"[-] Expected 200 OK for valid claim, got: {res.status_code} {res.text}")
        sys.exit(1)
        
    print("[+] Successfully claimed task with valid identity")
    
    # 4. Try complete with openclaw credentials (should fail)
    complete_payload = {
        "task_id": task_id,
        "worker_id": "hermes-test-worker",
        "result_summary": "Test complete",
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16)
    }
    
    res = make_signed_worker_post("cvn-complete-task", complete_payload, OC_KEY_ID, OC_BEARER, OC_HMAC)
    if res.status_code != 403:
        print(f"[-] Expected 403 Forbidden for cross-target complete, got: {res.status_code} {res.text}")
        sys.exit(1)
        
    print("[+] Correctly rejected complete from wrong target identity (403)")
    
    # 5. Complete with hermes credentials (should succeed)
    complete_payload["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    complete_payload["nonce"] = secrets.token_hex(16)
    
    res = make_signed_worker_post("cvn-complete-task", complete_payload, HERMES_KEY_ID, HERMES_BEARER, HERMES_HMAC)
    if res.status_code != 200:
        print(f"[-] Expected 200 OK for valid complete, got: {res.status_code} {res.text}")
        sys.exit(1)
        
    print("[+] Successfully completed task with valid identity")
    print("[*] All tests passed!")

if __name__ == "__main__":
    test_worker_identities()
