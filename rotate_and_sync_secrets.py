import os
import sys
import secrets
import keyring
import subprocess
import httpx
import json
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from app.destinations.payload_builder import build_payload
from app.destinations.hmac_signer import sign

SERVICE_NAME = "ClassroomVoiceNotes"
PROJECT_REF = "slvzyasosjiteimonzen"
ENDPOINT_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1/cvn-submit-task"

def main():
    print("=== Classroom Voice Notes: Secrets Sync & Deploy Tool ===")
    print(f"Project Reference: {PROJECT_REF}")
    print(f"Endpoint URL: {ENDPOINT_URL}\n")
    
    # 1. Check if logged into Supabase CLI
    print("[1/5] Checking Supabase CLI login status...")
    try:
        # Run a simple project list to check login status
        res = subprocess.run(
            ["npx", "supabase", "projects", "list"],
            capture_output=True,
            text=True,
            shell=True
        )
        if "Access token not provided" in res.stderr or "LegacyPlatformAuthRequiredError" in res.stderr or res.returncode != 0:
            print("[-] Supabase CLI is not logged in.")
            print("    Please run: npx supabase login")
            print("    in your terminal to authenticate first, then run this script again.\n")
            
            confirm = input("Would you like to generate the secrets and update your local keyring anyway? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Exiting.")
                return
            supabase_sync = False
        else:
            print("[+] Supabase CLI is logged in successfully.")
            supabase_sync = True
    except Exception as e:
        print(f"[-] Could not run Supabase CLI: {e}")
        confirm = input("Would you like to generate the secrets and update your local keyring anyway? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Exiting.")
            return
        supabase_sync = False

    # 2. Generate new secure secrets
    print("\n[2/5] Generating fresh cryptographically secure secrets...")
    new_hmac = secrets.token_hex(32)  # 64 hex chars
    new_bearer = secrets.token_hex(32)  # 64 hex chars
    print(f"[+] Generated new HMAC secret (ends in ...{new_hmac[-6:]})")
    print(f"[+] Generated new Bearer token (ends in ...{new_bearer[-6:]})")

    # 3. Save to local keyring
    print("\n[3/5] Saving secrets to Windows Credential Manager...")
    try:
        keyring.set_password(SERVICE_NAME, "cvn_hmac_secret", new_hmac)
        keyring.set_password(SERVICE_NAME, "cvn_bearer_token", new_bearer)
        print("[+] Secrets stored successfully in local keyring under 'ClassroomVoiceNotes'.")
    except Exception as e:
        print(f"[-] Failed to write to keyring: {e}")
        return

    # 4. Push to Supabase and redeploy function
    if supabase_sync:
        print("\n[4/5] Pushing secrets to Supabase and redeploying Edge Function...")
        # Set secrets
        secrets_cmd = [
            "npx", "supabase", "secrets", "set",
            f"CVN_HMAC_SECRET={new_hmac}",
            f"CVN_BEARER_TOKEN={new_bearer}",
            "--project-ref", PROJECT_REF
        ]
        print(f"Running: npx supabase secrets set ... --project-ref {PROJECT_REF}")
        sec_res = subprocess.run(secrets_cmd, shell=True)
        if sec_res.returncode != 0:
            print("[-] Failed to set secrets in Supabase. Please check your permissions.")
            return
        print("[+] Secrets successfully set on Supabase website.")

        # Redeploy function to cycle container and load new env variables
        deploy_cmd = [
            "npx", "supabase", "functions", "deploy",
            "cvn-submit-task",
            "--no-verify-jwt",
            "--project-ref", PROJECT_REF
        ]
        print(f"\nRunning: npx supabase functions deploy cvn-submit-task --no-verify-jwt --project-ref {PROJECT_REF}")
        dep_res = subprocess.run(deploy_cmd, shell=True)
        if dep_res.returncode != 0:
            print("[-] Failed to redeploy Edge Function. Please deploy manually.")
            return
        print("[+] Edge Function successfully redeployed and container recycled!")
    else:
        print("\n[4/5] Skipping Supabase push (CLI not logged in).")
        print("!!! IMPORTANT !!!")
        print("Please copy the following values and update them on the Supabase website under Project Settings -> Edge Functions -> Secrets:")
        print(f"CVN_HMAC_SECRET:  {new_hmac}")
        print(f"CVN_BEARER_TOKEN: {new_bearer}")
        print("\nOnce you have updated them and redeployed your function, run a test.")

    # 5. Run end-to-end smoke test
    print("\n[5/5] Running end-to-end diagnostic smoke test...")
    classification = {
        "title": "Fractions lesson plan automated test",
        "summary": "This is an automated diagnostic test.",
        "category": "agent_task",
        "sensitivity": "non_sensitive"
    }
    
    payload, json_str, payload_hash = build_payload(
        classification_data=classification,
        source_device_id="smoke-test-auto",
        target_agent="hermes",
        checks_passed=["category_agent_task", "no_student_registry_match"]
    )
    
    hmac_signature = sign(json_str.encode("utf-8"), new_hmac)
    headers = {
        "Authorization": f"Bearer {new_bearer}",
        "x-cvn-signature": hmac_signature,
        "Content-Type": "application/json"
    }
    
    try:
        print(f"Posting test task {payload['task_id']} to {ENDPOINT_URL}...")
        response = httpx.post(ENDPOINT_URL, content=json_str, headers=headers, timeout=15.0)
        print(f"Response Status: {response.status_code}")
        print(f"Response Text: {response.text}")
        if response.status_code == 200:
            print("\n[+] SUCCESS! The smoke test completed successfully.")
            print("    Your local keyring and Supabase production broker are fully synchronized and working.")
        else:
            print(f"\n[-] FAILED: Server returned status {response.status_code}.")
            print("    If you manual-copied the values, make sure the Edge Function container has finished recycling (wait 5 minutes).")
    except Exception as e:
        print(f"\n[-] HTTP request failed: {e}")

if __name__ == "__main__":
    main()
