# watch_inbox_dummy.py
import os
import sys
import time
import secrets
import datetime
import hashlib
import hmac
import requests
import json

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

BASE_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1"
CLAIM_URL = f"{BASE_URL}/cvn-claim-task"
COMPLETE_URL = f"{BASE_URL}/cvn-complete-task"

# Read secrets
AGENT_BROKER_BEARER_TOKEN = os.getenv("AGENT_BROKER_BEARER_TOKEN")
AGENT_BROKER_HMAC_SECRET = os.getenv("AGENT_BROKER_HMAC_SECRET")

if not AGENT_BROKER_BEARER_TOKEN or not AGENT_BROKER_HMAC_SECRET:
    print("[-] Error: AGENT_BROKER_BEARER_TOKEN and AGENT_BROKER_HMAC_SECRET must be set as environment variables.")
    sys.exit(1)

def sign_body(body_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

def make_signed_post(url: str, payload: dict) -> requests.Response:
    body_str = json.dumps(payload, separators=(",", ":"))
    body_bytes = body_str.encode("utf-8")
    sig = sign_body(body_bytes, AGENT_BROKER_HMAC_SECRET)
    headers = {
        "Authorization": f"Bearer {AGENT_BROKER_BEARER_TOKEN}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }
    return requests.post(url, data=body_bytes, headers=headers, timeout=15.0)

def poll_and_process():
    worker_id = "dummy-worker-001"
    
    print(f"\n[+] Polling {CLAIM_URL} for tasks...")
    
    now = datetime.datetime.now(datetime.timezone.utc)
    claim_payload = {
        "worker_id": worker_id,
        "vt_seconds": 1800,
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    
    try:
        res = make_signed_post(CLAIM_URL, claim_payload)
        if res.status_code != 200:
            print(f"[-] Claim request returned status {res.status_code}: {res.text}")
            return
        
        data = res.json()
        if not data.get("claimed"):
            print("[-] No pending tasks in queue.")
            return
        
        task_id = data["task_id"]
        target_agent = data["target_agent"]
        payload = data["payload"]
        
        print(f"[+] CLAIMED TASK: {task_id} (Target: {target_agent})")
        print(f"    Instructions: {payload.get('task', {}).get('instructions')}")
        
        # Wait 2 seconds
        print("[+] Simulating work for 2 seconds...")
        time.sleep(2.0)
        
        # Complete task
        print(f"[+] Completing task {task_id}...")
        complete_now = datetime.datetime.now(datetime.timezone.utc)
        complete_payload = {
            "task_id": task_id,
            "worker_id": worker_id,
            "result_summary": f"Completed by dummy worker at {complete_now.isoformat()}.",
            "signed_at": complete_now.isoformat(),
            "nonce": secrets.token_hex(16)
        }
        
        comp_res = make_signed_post(COMPLETE_URL, complete_payload)
        if comp_res.status_code == 200:
            print(f"[+] Task {task_id} completed successfully!")
        else:
            print(f"[-] Failed to complete task: Status {comp_res.status_code}: {comp_res.text}")
            
    except Exception as e:
        print(f"[-] Network or processing error: {e}")

def main():
    print("[+] Dummy worker started. Press Ctrl+C to stop.")
    poll_interval = int(os.getenv("DUMMY_POLL_INTERVAL", "5"))
    
    while True:
        poll_and_process()
        time.sleep(poll_interval)

if __name__ == "__main__":
    main()
