# watch_inbox_dummy.py
import os
import sys
import time
import secrets
import datetime
import requests
import json
import random

# Add project root to path for imports to find app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config.keyring_store import get_secret
from app.destinations.hmac_signer import sign

# Environment checks for safety
CVN_BROKER_ENV = os.getenv("CVN_BROKER_ENV", "staging").strip().lower()
CVN_ALLOW_PRODUCTION_WORKER = os.getenv("CVN_ALLOW_PRODUCTION_WORKER", "false").strip().lower()

if CVN_BROKER_ENV == "production":
    if CVN_ALLOW_PRODUCTION_WORKER != "true":
        print("[-] CRITICAL SAFETY GUARD: Refusing to run dummy worker against PRODUCTION.")
        print("    To run against production, you must set both:")
        print("    CVN_BROKER_ENV=production")
        print("    CVN_ALLOW_PRODUCTION_WORKER=true")
        sys.exit(1)
    else:
        print("[!] WARNING: Running dummy worker against PRODUCTION database!")
        PROJECT_REF = "slvzyasosjiteimonzen"
else:
    print("[+] Running dummy worker in STAGING mode.")
    PROJECT_REF = "ukqkkgzimhtjhlnmlyao"

# Generate a unique worker ID to support multiple parallel instances
WORKER_ID = f"dummy-worker-{secrets.token_hex(4)}"

def resolve_urls():
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

# Read secrets from environment or Windows Credential Manager
AGENT_BROKER_BEARER_TOKEN = os.getenv("AGENT_BROKER_BEARER_TOKEN") or get_secret("agent_broker_bearer_token")
AGENT_BROKER_HMAC_SECRET = os.getenv("AGENT_BROKER_HMAC_SECRET") or get_secret("agent_broker_hmac_secret")

if not AGENT_BROKER_BEARER_TOKEN or not AGENT_BROKER_HMAC_SECRET:
    print("[-] CRITICAL credential/configuration error: Worker secrets not found.")
    sys.exit(1)

def make_signed_post(url: str, payload: dict) -> requests.Response:
    body_str = json.dumps(payload, separators=(",", ":"))
    body_bytes = body_str.encode("utf-8")
    sig = sign(body_bytes, AGENT_BROKER_HMAC_SECRET)
    headers = {
        "Authorization": f"Bearer {AGENT_BROKER_BEARER_TOKEN}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }
    return requests.post(url, data=body_bytes, headers=headers, timeout=10.0)

def get_task_retry_count(task_id: str) -> int:
    now_status = datetime.datetime.now(datetime.timezone.utc)
    signed_at_str = now_status.isoformat()
    nonce_status = secrets.token_hex(16)
    canonical = f"GET\n/functions/v1/cvn-status/{task_id}\ntask_id={task_id}\nsigned_at={signed_at_str}\nnonce={nonce_status}"
    sig = sign(canonical.encode("utf-8"), AGENT_BROKER_HMAC_SECRET)
    
    url = f"{resolve_urls()['status']}/{task_id}"
    try:
        res = requests.get(
            url,
            params={
                "signed_at": signed_at_str,
                "nonce": nonce_status
            },
            headers={
                "Authorization": f"Bearer {AGENT_BROKER_BEARER_TOKEN}",
                "x-cvn-signature": sig
            },
            timeout=10.0
        )
        if res.status_code in (401, 403):
            print("[-] CRITICAL: Invalid credentials on status check (401/403). Stopping worker.")
            sys.exit(1)
        if res.status_code == 200:
            return res.json().get("retry_count", 0)
        else:
            print(f"[-] Warning: Failed to query task status to get retry count: status {res.status_code}")
            return 0
    except Exception as e:
        print(f"[-] Warning: Failed to query task status due to exception: {e}")
        return 0

def complete_task(task_id: str):
    worker_id = WORKER_ID
    now = datetime.datetime.now(datetime.timezone.utc)
    complete_payload = {
        "task_id": task_id,
        "worker_id": worker_id,
        "result_summary": "Completed successfully by dummy worker.",
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    print(f"[+] Submitting completion for task {task_id}...")
    res = make_signed_post(resolve_urls()["complete"], complete_payload)
    if res.status_code == 200:
        print(f"[+] Task {task_id} marked completed.")
    else:
        print(f"[-] Failed to complete task: status {res.status_code}")

def fail_task_retryable(task_id: str, error_msg: str):
    worker_id = WORKER_ID
    now = datetime.datetime.now(datetime.timezone.utc)
    fail_payload = {
        "task_id": task_id,
        "worker_id": worker_id,
        "error_message": error_msg,
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    print(f"[-] Submitting failure for task {task_id}: {error_msg}")
    res = make_signed_post(resolve_urls()["fail"], fail_payload)
    if res.status_code == 200:
        print(f"[+] Task {task_id} marked failed (requeued or dead-lettered).")
    else:
        print(f"[-] Failed to submit failure: status {res.status_code}")

def fail_task_permanently(task_id: str, error_msg: str):
    print(f"[!] Permanent task failure: {error_msg}")
    fail_task_retryable(task_id, f"Permanent validation error: {error_msg}")

def process_task(task_id: str, target_agent: str, payload: dict) -> bool:
    # 1. Validate payload structure (permanent error if malformed)
    if not isinstance(payload, dict) or "task" not in payload or "title" not in payload["task"] or "instructions" not in payload["task"]:
        print(f"[-] Malformed task payload. Failing permanently.")
        fail_task_permanently(task_id, "Malformed task payload: missing required fields")
        return False
        
    # Check schema version
    if payload.get("schema_version") != "cvn.agent_task.v1":
        print(f"[-] Unsupported schema version: {payload.get('schema_version')}. Failing permanently.")
        fail_task_permanently(task_id, f"Unsupported schema version: {payload.get('schema_version')}")
        return False
        
    task_instructions = payload["task"]["instructions"]
    
    # Try parsing as JSON to check if it's cvn.test
    try:
        inst_data = json.loads(task_instructions)
    except Exception:
        inst_data = {}
        
    task_type = inst_data.get("task_type")
    
    # Test-only instructions must only be accepted when task_type == "cvn.test".
    if task_type == "cvn.test":
        test_mode = inst_data.get("payload", {}).get("test_mode", "success")
        print(f"[+] Processing cvn.test task in mode: {test_mode}")
        
        if test_mode == "success":
            print("[+] Simulating processing for 2 seconds...")
            time.sleep(2.0)
            complete_task(task_id)
            return True
            
        elif test_mode == "fail_once":
            retry_count = get_task_retry_count(task_id)
            print(f"[+] fail_once task. Current DB retry_count: {retry_count}")
            
            if retry_count == 0:
                print("[-] First attempt. Failing task once...")
                fail_task_retryable(task_id, "Simulated first-attempt failure")
                return False
            else:
                print("[+] Subsequent attempt. Completing successfully...")
                complete_task(task_id)
                return True
                
        elif test_mode == "fail_always":
            print("[-] fail_always task. Failing task...")
            fail_task_retryable(task_id, "Simulated permanent retryable failure")
            return False
            
        elif test_mode == "delay":
            print("[+] delay task. Simulating long work for 5 seconds...")
            time.sleep(5.0)
            complete_task(task_id)
            return True
            
        elif test_mode == "crash_after_claim":
            retry_count = get_task_retry_count(task_id)
            print(f"[+] crash_after_claim task. Current DB retry_count: {retry_count}")
            if retry_count == 0:
                print("[!] crash_after_claim task (first claim). Terminating worker process immediately...")
                sys.exit(0)
            else:
                print("[+] crash_after_claim task (reclaimed after restart). Completing successfully...")
                complete_task(task_id)
                return True
            
        else:
            print(f"[-] Malformed/unsupported test mode: {test_mode}. Failing permanently.")
            fail_task_permanently(task_id, f"Unsupported test mode: {test_mode}")
            return False
    else:
        # Genuine classroom-note tasks (not cvn.test)
        print(f"[+] Processing genuine task: {payload['task']['title']}")
        try:
            print("[+] Simulating processing for 2 seconds...")
            time.sleep(2.0)
            complete_task(task_id)
            return True
        except Exception as e:
            print(f"[-] Unexpected processing error: {e}. Failing task...")
            fail_task_retryable(task_id, f"Unexpected processing error: {str(e)}")
            return False

def main():
    print(f"[+] Dummy worker {WORKER_ID} started. Press Ctrl+C to stop.")
    poll_interval = int(os.getenv("DUMMY_POLL_INTERVAL", "5"))
    worker_id = WORKER_ID
    
    backoff_count = 0
    
    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            claim_payload = {
                "worker_id": worker_id,
                "vt_seconds": 1800,  # 30 mins
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
                
            # Reset backoff count on successful 200 response
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
