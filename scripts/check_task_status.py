#!/usr/bin/env python
# scripts/check_task_status.py
import argparse
import sys
import os
import requests
import datetime
import secrets

# Add project root to path for imports to find app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.keyring_store import get_secret
from app.config.environment import get_broker_env, get_env_credential_ref
from app.destinations.hmac_signer import sign

def main():
    parser = argparse.ArgumentParser(description="Query the status of a CVN task safely.")
    parser.add_argument("task_id", help="The Task ID to check (e.g. CVN-YYYYMMDD-HHMMSS-XXXX)")
    args = parser.parse_args()

    if get_broker_env() != "staging":
        print("[-] CRITICAL: This status helper is restricted to CVN_BROKER_ENV=staging.")
        sys.exit(1)

    # Load the same environment-scoped credentials used by the desktop app.
    CLIENT_BEARER = get_secret(get_env_credential_ref("bearer_token"))
    CLIENT_HMAC = get_secret(get_env_credential_ref("hmac_secret"))

    if not CLIENT_BEARER or not CLIENT_HMAC:
        print("[-] CRITICAL: Client credentials not found in Windows Credential Manager under 'ClassroomVoiceNotes'.")
        sys.exit(1)

    PROJECT_REF = "ukqkkgzimhtjhlnmlyao"
    STATUS_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1/cvn-status/{args.task_id}"

    # Setup signed request details
    now = datetime.datetime.now(datetime.timezone.utc)
    signed_at_str = now.isoformat()
    nonce = secrets.token_hex(16)

    # Canonical string: GET\n/functions/v1/cvn-status/<task_id>\ntask_id=<task_id>\nsigned_at=<signed_at>\nnonce=<nonce>
    canonical = f"GET\n/functions/v1/cvn-status/{args.task_id}\ntask_id={args.task_id}\nsigned_at={signed_at_str}\nnonce={nonce}"
    sig = sign(canonical.encode("utf-8"), CLIENT_HMAC)

    print(f"[*] Fetching status for task {args.task_id}...")
    try:
        # Use requests.get(..., params=...) so '+10:00' timezone is properly URL encoded to '%2B10:00'
        res = requests.get(
            STATUS_URL,
            params={
                "signed_at": signed_at_str,
                "nonce": nonce
            },
            headers={
                "Authorization": f"Bearer {CLIENT_BEARER}",
                "x-cvn-signature": sig
            },
            timeout=10.0
        )

        if res.status_code == 200:
            data = res.json()
            print("\n=== Task Status Details ===")
            for key, val in data.items():
                print(f"{key:16}: {val}")
        elif res.status_code == 404:
            print(f"[-] Task not found: {args.task_id}")
        else:
            print(f"[-] Status check failed (status {res.status_code}): {res.text}")
            sys.exit(1)

    except Exception as e:
        print(f"[-] HTTP Request failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
