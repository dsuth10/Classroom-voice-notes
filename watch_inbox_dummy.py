# watch_inbox_dummy.py
import os
import sys
import time
import secrets
import datetime
import requests
import json
import random
from typing import Dict, Any

# Add project root to path for imports to find app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config.keyring_store import get_secret
from app.destinations.hmac_signer import sign
from app.destinations.dummy_adapter import DummyAdapter
from app.worker.errors import WorkerError

# Environment checks for safety
CVN_BROKER_ENV = os.getenv("CVN_BROKER_ENV", "").strip()
CVN_ALLOW_PRODUCTION_WORKER = os.getenv("CVN_ALLOW_PRODUCTION_WORKER", "false").strip().lower()

if CVN_BROKER_ENV == "production":
    if CVN_ALLOW_PRODUCTION_WORKER != "true":
        print("[-] CRITICAL SAFETY GUARD: Refusing to run dummy worker against PRODUCTION.")
        sys.exit(1)
    else:
        print("[!] WARNING: Running dummy worker against PRODUCTION database!")
        PROJECT_REF = "slvzyasosjiteimonzen"
elif CVN_BROKER_ENV != "staging":
    print(f"[-] ERROR: CVN_BROKER_ENV must equal exactly 'staging' or 'production'. Found: '{CVN_BROKER_ENV}'")
    sys.exit(1)
else:
    print("[+] Running dummy worker in STAGING mode.")
    PROJECT_REF = "ukqkkgzimhtjhlnmlyao"

WORKER_ID = f"dummy-worker-{secrets.token_hex(4)}"

def resolve_urls() -> Dict[str, str]:
    if CVN_BROKER_ENV == "production":
        ref = "slvzyasosjiteimonzen"
    else:
        ref = "ukqkkgzimhtjhlnmlyao"

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "network_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
                ref = data.get("project_ref", ref)
        except Exception:
            pass
    base = f"https://{ref}.supabase.co/functions/v1"
    return {
        "claim": f"{base}/cvn-claim-task",
        "complete": f"{base}/cvn-complete-task",
        "fail": f"{base}/cvn-fail-task",
        "status": f"{base}/cvn-status"
    }

AGENT_BROKER_BEARER_TOKEN = os.getenv("AGENT_BROKER_BEARER_TOKEN") or get_secret("agent_broker_bearer_token")
AGENT_BROKER_HMAC_SECRET = os.getenv("AGENT_BROKER_HMAC_SECRET") or get_secret("agent_broker_hmac_secret")
AGENT_BROKER_KEY_ID = os.getenv("AGENT_BROKER_KEY_ID")

if not AGENT_BROKER_BEARER_TOKEN or not AGENT_BROKER_HMAC_SECRET:
    print("[-] CRITICAL credential/configuration error: Worker secrets not found.")
    sys.exit(1)

def make_signed_post(url: str, payload: Dict[str, Any]) -> requests.Response:
    assert AGENT_BROKER_HMAC_SECRET is not None
    assert AGENT_BROKER_BEARER_TOKEN is not None
    body_str = json.dumps(payload, separators=(",", ":"))
    body_bytes = body_str.encode("utf-8")
    sig = sign(body_bytes, AGENT_BROKER_HMAC_SECRET)
    headers = {
        "Authorization": f"Bearer {AGENT_BROKER_BEARER_TOKEN}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }
    if AGENT_BROKER_KEY_ID:
        headers["x-cvn-key-id"] = AGENT_BROKER_KEY_ID
    return requests.post(url, data=body_bytes, headers=headers, timeout=10.0)

def complete_task(task_id: str, summary: str) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    complete_payload = {
        "task_id": task_id,
        "worker_id": WORKER_ID,
        "result_summary": summary,
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    print(f"[+] Submitting completion for task {task_id}...")
    res = make_signed_post(resolve_urls()["complete"], complete_payload)
    if res.status_code == 200:
        print(f"[+] Task {task_id} marked completed.")
    else:
        print(f"[-] Failed to complete task: status {res.status_code}")

def fail_task(task_id: str, error_msg: str, error_code: str, disposition: str) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    fail_payload = {
        "task_id": task_id,
        "worker_id": WORKER_ID,
        "failure": {
            "code": error_code,
            "message": error_msg,
            "disposition": disposition
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    print(f"[-] Submitting failure for task {task_id} (disposition: {disposition}): {error_msg}")
    res = make_signed_post(resolve_urls()["fail"], fail_payload)
    if res.status_code == 200:
        print(f"[+] Task {task_id} marked failed.")
    else:
        print(f"[-] Failed to submit failure: status {res.status_code}")

def process_task(task_id: str, target_agent: str, payload: Dict[str, Any]) -> bool:
    adapter = DummyAdapter()

    # Validate task
    try:
        adapter.validate_task(payload)
    except WorkerError as e:
        print(f"[-] Permanent validation error: {e}")
        fail_task(task_id, str(e), type(e).__name__, "permanent")
        return False
    except Exception as e:
        print(f"[-] Transient validation error: {e}")
        fail_task(task_id, str(e), "VALIDATION_ERROR", "retryable")
        return False

    # Convert task
    try:
        request = adapter.convert_task(payload)
    except Exception as e:
        print(f"[-] Conversion error: {e}")
        fail_task(task_id, f"Conversion error: {str(e)}", "CONVERSION_ERROR", "permanent")
        return False

    # Execute task
    try:
        response = adapter.execute(request, 10)
    except WorkerError as e:
        print(f"[-] Dummy execution error: {e}")
        fail_task(task_id, str(e), type(e).__name__, "retryable")
        return False
    except Exception as e:
        print(f"[-] Unexpected execution error: {e}")
        fail_task(task_id, str(e), "EXECUTION_ERROR", "retryable")
        return False

    # Validate response
    try:
        result = adapter.validate_response(response)
    except WorkerError as e:
        print(f"[-] Response validation error: {e}")
        fail_task(task_id, str(e), type(e).__name__, "permanent")
        return False
    except Exception as e:
        print(f"[-] Unexpected response validation error: {e}")
        fail_task(task_id, str(e), "RESPONSE_VALIDATION_ERROR", "permanent")
        return False

    # Complete
    complete_task(task_id, result["result_summary"])
    return True

def main() -> None:
    print(f"[+] Dummy worker {WORKER_ID} started. Press Ctrl+C to stop.")
    poll_interval = int(os.getenv("DUMMY_POLL_INTERVAL", "5"))
    worker_id = WORKER_ID

    backoff_count = 0

    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            claim_payload = {
                "worker_id": worker_id,
                "vt_seconds": 1800,
                "target_agent": "hermes",
                "signed_at": now.isoformat(),
                "nonce": secrets.token_hex(16)
            }

            urls = resolve_urls()
            print(f"\n[+] Polling {urls['claim']} for tasks...")
            res = make_signed_post(urls["claim"], claim_payload)

            if res.status_code in (401, 403):
                print(f"[-] CRITICAL: HTTP {res.status_code} Unauthorized. Stopping worker.")
                sys.exit(1)

            if res.status_code != 200:
                print(f"[-] Claim request returned status {res.status_code}")
                backoff_count += 1
                backoff_sec = min(30, 2 ** backoff_count)
                jitter = random.uniform(0, 1.0)
                sleep_time = backoff_sec + jitter
                print(f"[-] Backing off for {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                continue

            backoff_count = 0

            data = res.json()
            if not data.get("claimed"):
                print("[-] No pending tasks in queue.")
                time.sleep(poll_interval)
                continue

            task_id = data["task_id"]
            target_agent = data["target_agent"]
            payload = data["payload"]

            print(f"[+] CLAIMED TASK: {task_id} (Target Agent: {target_agent})")
            process_task(task_id, target_agent, payload)

        except requests.exceptions.RequestException as e:
            print(f"[-] Network error/timeout: {e}")
            backoff_count += 1
            backoff_sec = min(30, 2 ** backoff_count)
            jitter = random.uniform(0, 1.0)
            sleep_time = backoff_sec + jitter
            print(f"[-] Backing off for {sleep_time:.2f}s...")
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("\n[+] Ctrl+C detected. Exiting cleanly.")
            break
        except Exception as e:
            print(f"[-] Unexpected error in worker loop: {e}")
            time.sleep(poll_interval)

if __name__ == "__main__":
    main()
