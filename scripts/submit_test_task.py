#!/usr/bin/env python
# scripts/submit_test_task.py
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

def main():
    parser = argparse.ArgumentParser(description="Submit a test task to the CVN broker queue.")
    parser.add_argument("--title", default="Phase 2B test task", help="Title of the task")
    parser.add_argument(
        "--mode",
        choices=["success", "fail-once", "fail_once", "fail-always", "fail_always", "delay", "crash-after-claim", "crash_after_claim"],
        default="success",
        help="Test mode for the worker to execute"
    )
    args = parser.parse_args()

    # Map hyphens to underscores for the worker's processing
    test_mode = args.mode.replace("-", "_")

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
            "title": args.title,
            "test_mode": test_mode
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

    # Build the payload envelope
    payload, json_str, payload_hash = build_payload(
        classification_data=classification,
        source_device_id="cli-test-submitter",
        target_agent="hermes",
        checks_passed=["category_agent_task"]
    )

    task_id = payload["task_id"]

    # Sign the payload
    sig = sign(json_str.encode("utf-8"), CLIENT_HMAC)

    PROJECT_REF = "ukqkkgzimhtjhlnmlyao"
    SUBMIT_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1/cvn-submit-task"

    headers = {
        "Authorization": f"Bearer {CLIENT_BEARER}",
        "x-cvn-signature": sig,
        "Content-Type": "application/json"
    }

    print(f"[*] Submitting task {task_id} with mode '{test_mode}'...")
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
