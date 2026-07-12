#!/usr/bin/env python3
# deploy/diagnose_worker.py
import os
import sys
import json
import urllib.request
import urllib.error
from urllib.parse import urlparse
import datetime
from typing import Dict, Optional, Tuple

def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def test_http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 5.0) -> Tuple[Optional[int], str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except urllib.error.URLError as e:
        return None, str(e.reason)
    except Exception as e:
        return None, str(e)

def main() -> None:
    print("=== Classroom Voice Notes: VPS Staging Worker Diagnostics ===")
    
    # 1. Environment Variable Check
    print_section("1. Environment Configuration")
    broker_env = os.getenv("CVN_BROKER_ENV", "").strip()
    worker_id = os.getenv("CVN_WORKER_ID")
    key_id = os.getenv("AGENT_BROKER_KEY_ID")
    target_agent = os.getenv("CVN_TARGET_AGENT")
    
    print(f"CVN_BROKER_ENV     : {broker_env} (Expected: staging)")
    print(f"CVN_WORKER_ID      : {worker_id} (Expected: vps-worker-id-staging)")
    print(f"AGENT_BROKER_KEY_ID: {key_id} (Expected: vps-worker-staging)")
    print(f"CVN_TARGET_AGENT   : {target_agent} (Expected: openclaw)")
    
    errors = 0
    if broker_env != "staging":
        print("[-] ERROR: CVN_BROKER_ENV is not set to 'staging'.")
        errors += 1
    if not worker_id:
        print("[-] ERROR: CVN_WORKER_ID environment variable is missing.")
        errors += 1
    if not key_id:
        print("[-] ERROR: AGENT_BROKER_KEY_ID environment variable is missing.")
        errors += 1
    if target_agent != "openclaw":
        print("[-] ERROR: CVN_TARGET_AGENT is not 'openclaw'.")
        errors += 1
        
    if errors == 0:
        print("[+] Environment variables are correctly configured.")
    else:
        print(f"[-] Total environment configuration errors: {errors}")

    # 2. Credential Resolution Checks (systemd or file-based)
    print_section("2. Credential Security & Accessibility")
    creds = {
        "AGENT_BROKER_BEARER_TOKEN_FILE": os.getenv("AGENT_BROKER_BEARER_TOKEN_FILE"),
        "AGENT_BROKER_HMAC_SECRET_FILE": os.getenv("AGENT_BROKER_HMAC_SECRET_FILE"),
        "OPENCLAW_GATEWAY_TOKEN_FILE": os.getenv("OPENCLAW_GATEWAY_TOKEN_FILE")
    }
    
    gateway_token_val = None
    cred_errors = 0
    for name, path in creds.items():
        if not path:
            print(f"[-] WARNING: {name} environment variable is not defined.")
            cred_errors += 1
            continue
            
        print(f"Checking {name} -> {path}:")
        if not os.path.exists(path):
            print(f"  [-] ERROR: Credential file does not exist at '{path}'")
            cred_errors += 1
            continue
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                val = f.read().strip()
                size = len(val)
                if size == 0:
                    print(f"  [-] ERROR: Credential file at '{path}' is empty.")
                    cred_errors += 1
                else:
                    print(f"  [+] SUCCESS: Readable, size: {size} chars.")
                    if name == "OPENCLAW_GATEWAY_TOKEN_FILE":
                        gateway_token_val = val
        except Exception as e:
            print(f"  [-] ERROR: Failed to read credential file: {e}")
            cred_errors += 1

    # 3. Supabase Staging Connectivity
    print_section("3. Supabase Staging Connectivity")
    project_ref = "ukqkkgzimhtjhlnmlyao"
    supabase_host = f"{project_ref}.supabase.co"
    print(f"Resolving DNS for {supabase_host}...")
    try:
        import socket
        ip_addr = socket.gethostbyname(supabase_host)
        print(f"[+] DNS check successful. IP address: {ip_addr}")
    except Exception as e:
        print(f"[-] DNS check failed: {e}")
        errors += 1
        
    status_url = f"https://{project_ref}.supabase.co/functions/v1/cvn-status/CVN-20260712-102230-TEST"
    print("Testing HTTPS connectivity to cvn-status...")
    status_code, body = test_http_get(status_url)
    if status_code in (400, 401, 403, 404):
        print(f"[+] HTTPS connectivity check successful. HTTP status returned: {status_code}")
    else:
        print(f"[-] HTTPS connectivity check returned unexpected status {status_code}: {body}")
        errors += 1

    # 4. OpenClaw Gateway Checks
    print_section("4. Local OpenClaw Gateway Connectivity")
    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789").strip()
    print(f"OpenClaw Gateway URL: {gateway_url}")
    
    parsed_gateway = urlparse(gateway_url)
    scheme = parsed_gateway.scheme.lower() if parsed_gateway.scheme else ""
    
    is_valid_loopback = False
    if scheme in ("http+unix", "unix"):
        is_valid_loopback = True
        print("[+] Gateway URL is a Unix socket (valid loopback).")
    elif scheme in ("http", "https"):
        hostname = parsed_gateway.hostname.lower() if parsed_gateway.hostname else ""
        if hostname in ("127.0.0.1", "localhost", "::1"):
            is_valid_loopback = True
            print("[+] Gateway URL points to a local loopback IP/hostname.")
            
    if not is_valid_loopback:
        print(f"[-] ERROR: Gateway URL '{gateway_url}' is not a local loopback endpoint or Unix socket.")
        errors += 1

    # Check if we have the gateway token
    gateway_headers = {}
    if gateway_token_val:
        gateway_headers["Authorization"] = f"Bearer {gateway_token_val}"
    else:
        # Check if direct env is available
        direct_tok = os.getenv("OPENCLAW_GATEWAY_TOKEN")
        if direct_tok:
            gateway_headers["Authorization"] = f"Bearer {direct_tok}"
            gateway_token_val = direct_tok
            print("[+] Found OPENCLAW_GATEWAY_TOKEN directly in environment.")
        else:
            print("[-] WARNING: No gateway token resolved. Requests to gateway will be unauthenticated.")

    models_url = f"{gateway_url}/v1/models"
    print(f"Requesting models list from {models_url}...")
    status_code, body = test_http_get(models_url, headers=gateway_headers)
    
    if status_code == 200:
        try:
            data = json.loads(body)
            models = [m.get("id") for m in data.get("data", [])]
            print(f"[+] Gateway connection successful. Available models: {models}")
            
            expected_model = "openclaw/cvn-broker"
            if expected_model in models:
                print(f"[+] SUCCESS: Restricted model '{expected_model}' is available.")
            else:
                print(f"[-] ERROR: Restricted model '{expected_model}' is not registered in the gateway models list.")
                errors += 1
        except Exception as e:
            print(f"[-] ERROR: Failed to parse models list response: {e}")
            errors += 1
    elif status_code is None:
        print(f"[-] ERROR: Gateway is unreachable: {body}")
        errors += 1
    else:
        print(f"[-] ERROR: Gateway returned HTTP status {status_code}: {body}")
        errors += 1

    # 5. Time Synchronization Checks
    print_section("5. Time Synchronization Check")
    local_utc = datetime.datetime.now(datetime.timezone.utc)
    print(f"Local System UTC Time: {local_utc.isoformat()}")
    
    # Query worldtimeapi or similar to verify system clock is not drifted
    print("Querying public time server to verify clock sync...")
    time_status, time_body = test_http_get("http://worldtimeapi.org/api/timezone/Etc/UTC", timeout=3.0)
    if time_status == 200:
        try:
            time_data = json.loads(time_body)
            ref_time_str = time_data.get("utc_datetime")
            # Parse it
            ref_time = datetime.datetime.fromisoformat(ref_time_str.replace("Z", "+00:00"))
            drift = abs((local_utc - ref_time).total_seconds())
            print(f"Public Time Server UTC: {ref_time.isoformat()}")
            print(f"Calculated clock drift: {drift:.2f} seconds")
            if drift > 15.0:
                print(f"[-] ERROR: Clock drift is {drift:.2f}s, which exceeds the allowable HMAC signature window of 15 seconds.")
                errors += 1
            else:
                print("[+] SUCCESS: Clock drift is within normal tolerances.")
        except Exception as e:
            print(f"[!] Unable to verify clock drift dynamically (parse error): {e}")
    else:
        print(f"[!] Unable to contact public time server (connectivity): {time_body}")
        print("[!] Make sure NTP is active and timedatectl shows 'System clock synchronized: yes'")

    print_section("Diagnostic Summary")
    total_problems = errors + cred_errors
    if total_problems == 0:
        print("[+] ALL CHECKS PASSED. VPS environment is fully ready for staging worker activation.")
        sys.exit(0)
    else:
        print(f"[-] FAILED. Found {total_problems} problems that must be fixed before activating the service.")
        sys.exit(1)

if __name__ == "__main__":
    main()
