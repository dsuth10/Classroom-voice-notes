#!/usr/bin/env python
# deploy/wait_for_gateway.py
import os
import sys
import time
import json
import urllib.request
import urllib.error
from urllib.parse import urlparse
from typing import Any

def check_gateway() -> bool:
    gateway_url = "http://127.0.0.1:18789/v1/models"
    token_file = os.getenv("OPENCLAW_GATEWAY_TOKEN_FILE")
    if not token_file:
        print("[-] ERROR: OPENCLAW_GATEWAY_TOKEN_FILE environment variable is missing.")
        return False

    if not os.path.exists(token_file):
        print(f"[-] ERROR: Gateway token file path does not exist: {token_file}")
        return False

    # Check size limit (4KB)
    try:
        size = os.path.getsize(token_file)
        if size == 0:
            print("[-] ERROR: Gateway token file is empty.")
            return False
        if size > 4096:
            print("[-] ERROR: Gateway token file exceeds the reasonable size limit of 4KB.")
            return False
    except Exception as e:
        print(f"[-] ERROR: Cannot access gateway token file: {e}")
        return False

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            token = f.read().strip()
    except Exception as e:
        print(f"[-] ERROR: Gateway token file exists but cannot be read: {e}")
        return False

    if not token:
        print("[-] ERROR: Resolved gateway token is empty.")
        return False

    # Custom redirect handler to reject non-loopback destinations
    class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
            parsed = urlparse(newurl)
            hostname = parsed.hostname.lower() if parsed.hostname else ""
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                raise urllib.error.URLError("Redirect to non-loopback destination rejected")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(SafeRedirectHandler)
    req = urllib.request.Request(gateway_url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        # Perform request with a 3.0-second timeout
        with opener.open(req, timeout=3.0) as response:
            # We strictly require HTTP status 200
            if response.status != 200:
                print(f"[-] Gateway returned non-200 status code: {response.status}")
                return False

            # Bounded read: read at most 8KB of response
            body_bytes = response.read(8192)
            body_str = body_bytes.decode("utf-8", errors="ignore")

            # Parse JSON to verify structure
            data = json.loads(body_str)
            if isinstance(data, dict) and "data" in data:
                return True
            print("[-] Gateway response JSON is missing expected 'data' field.")
    except urllib.error.HTTPError as e:
        # e.code contains the HTTP status (e.g. 401, 403, 404, 500)
        # We explicitly fail on these.
        print(f"[-] Gateway HTTP error occurred: Status {e.code}")
    except json.JSONDecodeError:
        print("[-] Failed to parse gateway response as JSON.")
    except Exception as e:
        # Ensure token values never appear in exceptions.
        err_msg = str(e)
        if token and token in err_msg:
            err_msg = err_msg.replace(token, "[REDACTED]")
        print(f"[-] Gateway connection failed: {err_msg}")

    return False

def main() -> None:
    max_retries = 30
    delay = 2
    print(f"[*] Waiting for local OpenClaw gateway at http://127.0.0.1:18789 (timeout: {max_retries * delay}s)...")
    for _ in range(max_retries):
        if check_gateway():
            print("[+] OpenClaw gateway is ready and reachable.")
            sys.exit(0)
        time.sleep(delay)
    print("[-] ERROR: OpenClaw gateway did not become ready within the timeout period.")
    sys.exit(1)

if __name__ == "__main__":
    main()
