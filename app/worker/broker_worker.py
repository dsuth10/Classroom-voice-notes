# app/worker/broker_worker.py
import os
import sys
import time
import secrets
import datetime
import random
import requests
import json
from typing import Dict, Any

from app.destinations.hmac_signer import sign
from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import (
    UnsupportedContractVersion,
    UnsupportedTaskType,
    UnsupportedTargetAgent,
    InvalidTaskPayload,
    GatewayAuthenticationError,
    GatewayUnavailableError,
    GatewayRateLimitError,
    GatewayConfigurationError,
    GatewayResponseError,
    ExecutionTimeoutUnknown,
    InvalidAgentResponse
)

# Environment variables to determine mode
CVN_BROKER_ENV = os.getenv("CVN_BROKER_ENV", "staging").strip().lower()
CVN_ALLOW_PRODUCTION_WORKER = os.getenv("CVN_ALLOW_PRODUCTION_WORKER", "false").strip().lower()

class BrokerWorker:
    """Production broker worker that claims and processes target-specific tasks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.worker_id = f"openclaw-worker-{secrets.token_hex(4)}"
        self.running = False
        
        # Resolve secrets
        self.bearer_token = self._resolve_secret(
            "AGENT_BROKER_BEARER_TOKEN",
            "AGENT_BROKER_BEARER_TOKEN_FILE",
            "agent_broker_bearer_token"
        )
        self.hmac_secret = self._resolve_secret(
            "AGENT_BROKER_HMAC_SECRET",
            "AGENT_BROKER_HMAC_SECRET_FILE",
            "agent_broker_hmac_secret"
        )
        self.gateway_token = self._resolve_secret(
            "OPENCLAW_GATEWAY_TOKEN",
            "OPENCLAW_GATEWAY_TOKEN_FILE",
            "openclaw_gateway_token"
        )
        self.key_id = os.getenv("AGENT_BROKER_KEY_ID")
        
        # Verify safety guards
        if CVN_BROKER_ENV == "production" and CVN_ALLOW_PRODUCTION_WORKER != "true":
            print("[-] CRITICAL SAFETY GUARD: Refusing to run worker against PRODUCTION.")
            sys.exit(1)
            
    def _resolve_secret(self, direct_var: str, file_var: str, keyring_ref: str) -> str:
        """Resolves secrets using systemd credential files, env variables, or keyring fallback."""
        # 1. Try file-based secret (systemd LoadCredential)
        file_path = os.getenv(file_var)
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                raise RuntimeError(f"Failed to read secret from file path '{file_path}' (from {file_var}): {e}")
                
        # 2. Try direct environment variable
        direct_val = os.getenv(direct_var)
        if direct_val:
            return direct_val
            
        # 3. Try keyring fallback (local development)
        try:
            from app.config.keyring_store import get_secret
            val = get_secret(keyring_ref)
            if val:
                return val
        except Exception:
            pass
            
        raise RuntimeError(f"Missing required secret configuration: {direct_var} or {file_var}")

    def resolve_urls(self) -> Dict[str, str]:
        if CVN_BROKER_ENV == "production":
            ref = "slvzyasosjiteimonzen"
        else:
            ref = "ukqkkgzimhtjhlnmlyao"
            
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scratch", "network_config.json")
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
        
    def make_signed_post(self, url: str, payload: Dict[str, Any]) -> requests.Response:
        body_str = json.dumps(payload, separators=(",", ":"))
        body_bytes = body_str.encode("utf-8")
        sig = sign(body_bytes, self.hmac_secret)
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "x-cvn-signature": sig,
            "Content-Type": "application/json"
        }
        if self.key_id:
            headers["x-cvn-key-id"] = self.key_id
        return requests.post(url, data=body_bytes, headers=headers, timeout=15.0)
        
    def complete_task(self, task_id: str, summary: str) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "task_id": task_id,
            "worker_id": self.worker_id,
            "result_summary": summary,
            "signed_at": now.isoformat(),
            "nonce": secrets.token_hex(16)
        }
        try:
            res = self.make_signed_post(self.resolve_urls()["complete"], payload)
            if res.status_code == 200:
                print(f"[+] Task {task_id} successfully completed.")
                return True
            else:
                print(f"[-] Failed to mark task {task_id} completed: status {res.status_code}")
                return False
        except Exception as e:
            print(f"[-] Network error completing task {task_id}: {e}")
            return False
            
    def fail_task(self, task_id: str, error_msg: str, error_code: str, disposition: str) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "task_id": task_id,
            "worker_id": self.worker_id,
            "failure": {
                "code": error_code,
                "message": error_msg,
                "disposition": disposition
            },
            "signed_at": now.isoformat(),
            "nonce": secrets.token_hex(16)
        }
        try:
            res = self.make_signed_post(self.resolve_urls()["fail"], payload)
            if res.status_code == 200:
                print(f"[+] Task {task_id} marked failed (disposition: {disposition}).")
                return True
            else:
                print(f"[-] Failed to submit failure for task {task_id}: status {res.status_code}")
                return False
        except Exception as e:
            print(f"[-] Network error submitting failure for task {task_id}: {e}")
            return False
            
    def process_claimed_task(self, task_id: str, target_agent: str, payload: Dict[str, Any]) -> None:
        # 1. Verify routing
        if target_agent != "openclaw":
            print(f"[-] CRITICAL PROTOCOL ERROR: Worker claimed a non-matching task target '{target_agent}'. Leaving unclaimed.")
            return
            
        adapter = OpenClawAdapter(self.config.get("openclaw", {}), self.gateway_token)
        
        # 2. Validate task envelope & type
        try:
            adapter.validate_task(payload)
        except (UnsupportedContractVersion, UnsupportedTaskType, UnsupportedTargetAgent, InvalidTaskPayload) as e:
            print(f"[-] Permanent validation failure on task {task_id}: {e}")
            self.fail_task(task_id, str(e), type(e).__name__, "permanent")
            return
        except Exception as e:
            print(f"[-] Transient validation failure on task {task_id}: {e}")
            self.fail_task(task_id, str(e), "VALIDATION_FAILED", "retryable")
            return
            
        # 3. Convert task
        try:
            request = adapter.convert_task(payload)
        except Exception as e:
            print(f"[-] Failed to convert task payload: {e}")
            self.fail_task(task_id, f"Conversion error: {str(e)}", "CONVERSION_ERROR", "permanent")
            return
            
        # 4. Execute through OpenClaw loopback
        timeout = self.config.get("openclaw", {}).get("normal_timeout_seconds", 120)
        try:
            response = adapter.execute(request, timeout)
        except ExecutionTimeoutUnknown as e:
            print(f"[!] Read timeout executing task {task_id}: {e}")
            self.fail_task(task_id, "Gateway read timeout occurred after successful dispatch.", "EXECUTION_TIMEOUT_UNKNOWN", "execution_unknown")
            return
        except (GatewayUnavailableError, GatewayRateLimitError) as e:
            print(f"[-] Transient gateway failure executing task {task_id}: {e}")
            self.fail_task(task_id, str(e), type(e).__name__, "retryable")
            return
        except GatewayResponseError as e:
            disposition = "retryable" if e.status_code >= 500 else "permanent"
            print(f"[-] Gateway response error {e.status_code} executing task {task_id}: {e}")
            self.fail_task(task_id, str(e), type(e).__name__, disposition)
            return
        except (GatewayAuthenticationError, GatewayConfigurationError) as e:
            print(f"[-] Fatal gateway configuration failure executing task {task_id}: {e}")
            self.fail_task(task_id, str(e), type(e).__name__, "permanent")
            print("[!] Shutting down worker to alert operator.")
            self.running = False
            return
        except Exception as e:
            print(f"[-] Unexpected error executing task {task_id}: {e}")
            self.fail_task(task_id, str(e), "UNEXPECTED_EXECUTION_ERROR", "retryable")
            return
            
        # 5. Validate and sanitise response
        try:
            sanitised_result = adapter.validate_response(response)
        except InvalidAgentResponse as e:
            print(f"[-] Invalid agent response on task {task_id}: {e}")
            self.fail_task(task_id, str(e), type(e).__name__, "permanent")
            return
        except Exception as e:
            print(f"[-] Unexpected error validating response for task {task_id}: {e}")
            self.fail_task(task_id, str(e), "UNEXPECTED_VALIDATION_ERROR", "permanent")
            return
            
        # 6. Complete task
        self.complete_task(task_id, sanitised_result["result_summary"])
        
    def poll_and_process(self) -> None:
        urls = self.resolve_urls()
        now = datetime.datetime.now(datetime.timezone.utc)
        claim_payload = {
            "worker_id": self.worker_id,
            "vt_seconds": 1800,
            "target_agent": "openclaw",
            "signed_at": now.isoformat(),
            "nonce": secrets.token_hex(16)
        }
        
        try:
            print(f"[+] Polling {urls['claim']}...")
            res = self.make_signed_post(urls["claim"], claim_payload)
            
            if res.status_code in (401, 403):
                print(f"[-] CRITICAL: HTTP {res.status_code} Unauthorized. Stopping worker.")
                self.running = False
                return
                
            if res.status_code != 200:
                print(f"[-] Claim request returned status {res.status_code}. Backing off.")
                self.apply_backoff()
                return
                
            self.backoff_count = 0  # reset backoff on success
            
            data = res.json()
            if not data.get("claimed"):
                print("[-] No pending tasks in queue.")
                return
                
            task_id = data["task_id"]
            target_agent = data["target_agent"]
            payload = data["payload"]
            
            print(f"[+] CLAIMED TASK: {task_id}")
            self.process_claimed_task(task_id, target_agent, payload)
            
        except requests.exceptions.RequestException as e:
            print(f"[-] Supabase network/timeout error: {e}")
            self.apply_backoff()
        except Exception as e:
            print(f"[-] Unexpected error in worker loop: {e}")
            
    def apply_backoff(self) -> None:
        self.backoff_count = getattr(self, "backoff_count", 0) + 1
        sec = min(30, 2 ** self.backoff_count)
        jitter = random.uniform(0, 1.0)
        total = sec + jitter
        print(f"[-] Backing off for {total:.2f} seconds...")
        time.sleep(total)
        
    def run(self) -> None:
        print(f"[+] Worker {self.worker_id} initialised (env: {CVN_BROKER_ENV}).")
        self.running = True
        self.backoff_count = 0
        poll_interval = int(self.config.get("poll_interval_seconds", 5))
        
        while self.running:
            try:
                self.poll_and_process()
                if self.running:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                print("\n[+] KeyboardInterrupt detected. Stopping worker.")
                self.running = False
            except Exception as e:
                print(f"[-] Worker error loop handler: {e}")
                time.sleep(poll_interval)
                
        print(f"[+] Worker {self.worker_id} stopped cleanly.")
