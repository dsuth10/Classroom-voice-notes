#!/usr/bin/env python
# scripts/run_integration_tests.py
# Loads secrets from Windows Credential Manager and runs the Milestone 2 integration test.
# Usage: python scripts/run_integration_tests.py
import os
import sys
import subprocess
import keyring

SERVICE_NAME = "ClassroomVoiceNotes"

def _load(key_name: str, env_name: str) -> str:
    val = keyring.get_password(SERVICE_NAME, key_name)
    if not val:
        print(f"[-] Secret not found in keyring: service='{SERVICE_NAME}' key='{key_name}'")
        print(f"    Run set_cvn_broker_secrets.py (or equivalent) to store it first.")
        sys.exit(1)
    return val

env = os.environ.copy()
env["CVN_BEARER_TOKEN"]           = _load("staging_cvn_bearer_token",   "CVN_BEARER_TOKEN")
env["CVN_HMAC_SECRET"]            = _load("staging_cvn_hmac_secret",    "CVN_HMAC_SECRET")
env["AGENT_BROKER_BEARER_TOKEN"]  = _load("agent_broker_bearer_token",  "AGENT_BROKER_BEARER_TOKEN")
env["AGENT_BROKER_HMAC_SECRET"]   = _load("agent_broker_hmac_secret",   "AGENT_BROKER_HMAC_SECRET")

print("[+] Secrets loaded from Windows Credential Manager.")
print("[+] Launching test_supabase_broker_milestone_2.py against STAGING...")

result = subprocess.run(
    [sys.executable, "tests/integration/test_supabase_broker_milestone_2.py"],
    env=env,
)
sys.exit(result.returncode)
