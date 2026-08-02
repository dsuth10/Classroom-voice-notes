#!/usr/bin/env python
# scripts/submit_test_task_openclaw.py
import argparse
import sys
import os
import requests
import json

# Add project root to path for imports to find app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.keyring_store import get_secret
from app.destinations.hmac_signer import sign
from app.destinations.payload_builder import build_payload

# Safety Guard: Explicitly require staging environment via CVN_BROKER_ENV (reject any other or missing value)
CVN_BROKER_ENV = os.getenv("CVN_BROKER_ENV", "").strip()
if CVN_BROKER_ENV != "staging":
    print(f"[-] CRITICAL SAFETY GUARD: Refusing to submit test tasks because CVN_BROKER_ENV is '{CVN_BROKER_ENV}'. It must equal exactly 'staging'.")
    sys.exit(1)

PROJECT_REF = "ukqkkgzimhtjhlnmlyao"

def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a test task to the OpenClaw broker queue on staging.")
    parser.add_argument("--title", default="Phase 2C2 test task", help="Title of the task")
    parser.add_argument("--target", default="openclaw", help="Target agent for routing (e.g. openclaw)")
    parser.add_argument("--text", default="Return exactly: CVN_OPENCLAW_STAGING_OK", help="Text payload for OpenClaw to return")
    parser.add_argument("--correlation-id", default="phase-2c2-live-20260712-001", help="Unique correlation identifier")
    args = parser.parse_args()

    if args.target != "openclaw":
        print(f"[-] ERROR: This test harness is restricted to 'openclaw' target agent only. Target '{args.target}' is rejected.")
        sys.exit(1)

    # Load client secrets
    CLIENT_BEARER = get_secret("staging_cvn_bearer_token") or get_secret("cvn_bearer_token")
    CLIENT_HMAC = get_secret("staging_cvn_hmac_secret") or get_secret("cvn_hmac_secret")

    if not CLIENT_BEARER or not CLIENT_HMAC:
        print("[-] CRITICAL: Client credentials not found in Windows Credential Manager under 'ClassroomVoiceNotes'.")
        sys.exit(1)

    # Construct instructions as JSON string representing the test task structure
    instructions_dict = {
        "task_type": "cvn.test",
        "payload": {
            "mode": "echo",
            "text": args.text,
            "correlation_id": args.correlation_id
        }
    }
    instructions_str = json.dumps(instructions_dict, separators=(",", ":"))

    classification = {
        "title": args.title,
        "summary": instructions_str,
        "category_fields": {
            "priority": "normal"
        }
    }

    # Build the payload envelope targeting args.target
    payload, json_str, payload_hash = build_payload(
        classification_data=classification,
        source_device_id="cli-test-submitter-openclaw",
        target_agent=args.target,
        checks_passed=["category_agent_task"]
    )

    task_id = payload["task_id"]

    # Sign the payload
    sig = sign(json_str.encode("utf-8"), CLIENT_HMAC)

    global PROJECT_REF
    SUBMIT_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1/cvn-submit-task"
    if "ukqkkgzimhtjhlnmlyao" not in SUBMIT_URL:
        print(f"[-] ERROR: Safety check failed. Submission URL '{SUBMIT_URL}' does not target the staging project reference 'ukqkkgzimhtjhlnmlyao'.")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {CLIENT_BEARER}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }

    print(f"[*] Submitting task {task_id} targeting '{args.target}'...")
    try:
        res = requests.post(SUBMIT_URL, data=json_str.encode("utf-8"), headers=headers, timeout=10.0)
        if res.status_code == 200:
            print(f"[+] Task submitted successfully. Task ID: {task_id}")
            print(f"    Check status using: python scripts/check_task_status.py {task_id}")
        else:
            print(f"[-] Submission failed (status {res.status_code}): {res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"[-] HTTP Request failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
