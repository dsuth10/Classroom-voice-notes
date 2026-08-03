"""Outbound Worker V2 — Capability-scoped, production worker implementation for v2 outbound items."""

import argparse
from dataclasses import dataclass
import json
import logging
import os
import random
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app.destinations.openclaw_adapter import OpenClawAdapter
from app.destinations.record_consumer import RecordConsumer
from app.worker.errors import (
    ExecutionTimeoutUnknown,
    GatewayAuthenticationError,
    GatewayConfigurationError,
    GatewayRateLimitError,
    GatewayResponseError,
    GatewayUnavailableError,
    InvalidAgentResponse,
    InvalidTaskPayload,
    UnsupportedContractVersion,
    UnsupportedTargetAgent,
    UnsupportedTaskType,
)
from app.worker.journal import JournalIdentityConflictError, WorkerJournal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("OutboundWorkerV2")

EX_CONFIG = 78  # Standard sysexits code for configuration / authentication failure


class FatalWorkerError(Exception):
    """Fatal configuration or authentication error triggering worker process exit."""

    pass


@dataclass
class WorkerHealthStats:
    """Typed metrics container for worker operational telemetry."""

    worker_id: str
    claim_count: int = 0
    complete_count: int = 0
    error_count: int = 0
    last_claim_at: Optional[float] = None
    last_complete_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "claim_count": self.claim_count,
            "complete_count": self.complete_count,
            "error_count": self.error_count,
            "last_claim_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_claim_at)) if self.last_claim_at else None,
            "last_complete_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_complete_at)) if self.last_complete_at else None,
        }


class OutboundWorkerV2:
    """Capability-scoped worker for claiming, processing, and completing v2 outbound items."""

    def __init__(
        self,
        edge_base_url: Optional[str] = None,
        worker_bearer_token: Optional[str] = None,
        worker_hmac_secret: Optional[str] = None,
        worker_id: Optional[str] = None,
        worker_key_id: Optional[str] = None,
        openclaw_gateway_token: Optional[str] = None,
        allowed_kinds: Optional[List[str]] = None,
        allowed_agents: Optional[List[str]] = None,
        poll_interval_seconds: float = 2.0,
        visibility_timeout_seconds: int = 300,
        journal: Optional[WorkerJournal] = None,
    ) -> None:
        sb_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        default_edge_url = f"{sb_url}/functions/v1" if sb_url else ""
        self.edge_base_url = (edge_base_url or os.environ.get("CVN_EDGE_BASE_URL") or default_edge_url).rstrip("/")
        self.worker_bearer_token = worker_bearer_token or os.environ.get("CVN_WORKER_BEARER_TOKEN", "")
        self.worker_hmac_secret = worker_hmac_secret or os.environ.get("CVN_WORKER_HMAC_SECRET", "")
        self.worker_id = worker_id or os.environ.get("CVN_WORKER_ID", "openclaw-worker-v2-1")
        self.worker_key_id = worker_key_id or os.environ.get("CVN_WORKER_KEY_ID", self.worker_id)
        self.openclaw_gateway_token = openclaw_gateway_token or os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

        self.allowed_kinds = allowed_kinds or ["record_only", "agent_task"]
        self.allowed_agents = allowed_agents or ["openclaw"]
        self.poll_interval = poll_interval_seconds
        self.visibility_timeout = visibility_timeout_seconds
        self.running = True

        self.backoff_current = self.poll_interval
        self.backoff_max = 60.0

        # Health metrics
        self.health_stats = WorkerHealthStats(worker_id=self.worker_id)

        # Initialize Journal
        self.journal = journal or WorkerJournal()
        self._last_purge_time = 0.0

        # Validate mandatory credentials and configuration
        self._validate_startup_config()

    def get_health_snapshot(self) -> Dict[str, Any]:
        """Returns typed, sanitized telemetry snapshot for monitoring."""
        return self.health_stats.to_dict()

    def _validate_startup_config(self) -> None:
        missing = []
        if not self.edge_base_url:
            missing.append("CVN_EDGE_BASE_URL (or SUPABASE_URL)")
        if not self.worker_bearer_token:
            missing.append("CVN_WORKER_BEARER_TOKEN")
        if not self.worker_hmac_secret:
            missing.append("CVN_WORKER_HMAC_SECRET")
        if not self.worker_id:
            missing.append("CVN_WORKER_ID")

        if missing:
            logger.error(f"FATAL_CONFIG_ERROR: Missing required worker configuration: {', '.join(missing)}")
            raise FatalWorkerError(f"Missing configuration: {', '.join(missing)}")

    def stop(self, *args: Any) -> None:
        logger.info(f"Worker {self.worker_id} received stop signal; shutting down gracefully.")
        self.running = False

    def _make_headers(self, method: str, path: str, body_str: str) -> Dict[str, str]:
        import hashlib
        import hmac
        import uuid

        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex

        canonical_text = f"{method.upper()}|{path}|{timestamp}|{nonce}|{body_str}"
        sig = hmac.new(
            self.worker_hmac_secret.encode("utf-8"),
            canonical_text.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "Authorization": f"Bearer {self.worker_bearer_token}",
            "Content-Type": "application/json",
            "X-CVN-Key-Id": self.worker_key_id,
            "X-CVN-Signature": sig,
            "X-CVN-Timestamp": timestamp,
            "X-CVN-Nonce": nonce,
        }

    def _send_edge_rpc(self, path_suffix: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Sends signed RPC request to Edge function."""
        url = f"{self.edge_base_url}/{path_suffix.lstrip('/')}"
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path or f"/functions/v1/{path_suffix.lstrip('/')}"

        body_str = json.dumps(payload)
        data = body_str.encode("utf-8")
        headers = self._make_headers("POST", path, body_str)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_status = getattr(resp, "status", getattr(resp, "code", 200))
                status_code = raw_status if isinstance(raw_status, int) else 200
                res_body = resp.read().decode("utf-8")
                res_json = json.loads(res_body) if res_body else {}
                return status_code, res_json
        except urllib.error.HTTPError as http_err:
            if http_err.code in (401, 403):
                logger.error(f"FATAL_AUTH_ERROR: Edge endpoint returned HTTP {http_err.code} for path {path_suffix}")
                raise FatalWorkerError(f"Authentication failure: HTTP {http_err.code}")
            res_body = http_err.read().decode("utf-8") if http_err.fp else ""
            res_json = {}
            if res_body:
                try:
                    res_json = json.loads(res_body)
                except Exception:
                    pass
            return http_err.code, res_json

    def claim_item(self) -> Optional[Dict[str, Any]]:
        """Claims next item via Edge endpoint. Handles network backoff & fatal auth errors."""
        payload = {
            "worker_id": self.worker_id,
            "visibility_timeout_seconds": self.visibility_timeout,
            "allowed_kinds": self.allowed_kinds,
            "allowed_agents": self.allowed_agents,
        }

        try:
            status_code, res_json = self._send_edge_rpc("cvn-claim-outbound-item", payload)
            if status_code == 200 and isinstance(res_json, dict) and res_json.get("claimed"):
                self.backoff_current = self.poll_interval
                self.health_stats.claim_count += 1
                self.health_stats.last_claim_at = time.time()
                return res_json
            elif status_code in (429, 500, 502, 503, 504):
                logger.warning(f"RATE_LIMIT_OR_SERVER_ERROR: Claim RPC returned HTTP {status_code}; applying backoff.")
                self._apply_backoff()
            return None
        except FatalWorkerError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            logger.warning(f"NETWORK_TRANSIENT_ERROR: Claim request network issue: {net_err}")
            self._apply_backoff()
            return None

    def _apply_backoff(self) -> None:
        jitter = random.uniform(0.0, 0.5)
        sleep_time = min(self.backoff_current + jitter, self.backoff_max)
        logger.info(f"Applying backoff sleep of {sleep_time:.2f}s")
        time.sleep(sleep_time)
        self.backoff_current = min(self.backoff_current * 1.5, self.backoff_max)

    def validate_claimed_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Strictly validates raw claimed item from Edge RPC against exact v2 contract.

        Raises ValueError if claim or payload is invalid, missing mandatory fields, tampered, or contradictory.
        Returns the parsed inner payload dict.
        """
        if not isinstance(item, dict):
            raise ValueError("Claim item must be a dictionary")

        item_id = item.get("item_id")
        if not item_id or not isinstance(item_id, str):
            raise ValueError("Claim missing non-empty item_id string")

        lease_token = item.get("lease_token")
        if not lease_token or not isinstance(lease_token, str):
            raise ValueError("Claim missing non-empty lease_token string")

        item_kind = item.get("item_kind")
        if item_kind not in ("record_only", "agent_task"):
            raise ValueError(f"Claim item_kind '{item_kind}' is missing or unsupported")

        target_agent = item.get("target_agent")
        if not target_agent or not isinstance(target_agent, str):
            raise ValueError("Claim missing non-empty target_agent string")
        if target_agent in ("auto", "local", "none"):
            raise ValueError(f"Claim target_agent '{target_agent}' is forbidden; exact target required")

        if target_agent != "openclaw":
            raise ValueError(f"Invalid target_agent '{target_agent}'; expected 'openclaw'")

        payload_hash = item.get("payload_hash")
        if not payload_hash or not isinstance(payload_hash, str) or not re.match(r"^sha256:[0-9a-f]{64}$", payload_hash):
            raise ValueError("Claim payload_hash must match 'sha256:<64-hex-chars>' format")

        content_hash = item.get("content_hash")
        if not content_hash or not isinstance(content_hash, str) or not re.match(r"^[0-9a-f]{64}$", content_hash):
            raise ValueError("Claim content_hash must be a 64-character hex SHA-256 string")

        payload = item.get("payload")
        if payload is None and "payload_json" in item:
            payload = item["payload_json"]
        if not isinstance(payload, dict):
            raise ValueError("Claim payload must be a dictionary")

        # Mandatory Inner Envelope Agreement Checks
        schema_ver = payload.get("schema_version")
        if not schema_ver or schema_ver != "cvn.outbound_item.v2":
            raise ValueError(f"Payload schema_version '{schema_ver}' is missing or unsupported; expected 'cvn.outbound_item.v2'")

        in_item_id = payload.get("item_id")
        if not in_item_id or in_item_id != item_id:
            raise ValueError(f"Inner payload item_id '{in_item_id}' is missing or contradicts outer claim item_id '{item_id}'")

        in_item_kind = payload.get("item_kind")
        if not in_item_kind or in_item_kind != item_kind:
            raise ValueError(f"Inner payload item_kind '{in_item_kind}' is missing or contradicts outer claim item_kind '{item_kind}'")

        in_target_agent = payload.get("target_agent")
        if not in_target_agent or in_target_agent != target_agent:
            raise ValueError(f"Inner payload target_agent '{in_target_agent}' is missing or contradicts outer claim target_agent '{target_agent}'")

        in_content_hash = payload.get("content_hash")
        if not in_content_hash or in_content_hash != content_hash:
            raise ValueError("Inner payload content_hash is missing or contradicts outer claim content_hash")

        # Lease expiry validation
        lease_expires_at = item.get("lease_expires_at")
        if lease_expires_at is not None:
            if time.time() >= float(lease_expires_at):
                raise ValueError(f"Claim lease expired at {lease_expires_at}")

        # Recompute canonical content hash from content and task
        try:
            from app.destinations.canonical_json import compute_canonical_content_hash
            content = payload.get("content")
            task = payload.get("task")
            _, calc_hash = compute_canonical_content_hash(item_kind, target_agent, content, task)
            if calc_hash != content_hash:
                raise ValueError(f"Recomputed canonical content_hash '{calc_hash}' does not match claimed content_hash '{content_hash}'")
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Failed canonical content hash recomputation: {exc}") from exc

        return payload

    def route_and_process(self, item: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Routes item to exact capability consumer.

        Returns (success: bool, error_code_or_ref: str, result_dict: Optional[Dict[str, Any]]).
        Raises FatalWorkerError on gateway authentication / configuration failure.
        """
        item_id = item.get("item_id", "")
        item_kind = item.get("item_kind") or item.get("kind") or ""
        target_agent = item.get("target_agent") or item.get("target") or ""

        # Check routing
        if item_kind == "record_only":
            if target_agent != "openclaw":
                logger.error(f"INVALID_ROUTING: record_only item {item_id} has unexpected target_agent '{target_agent}'")
                return False, "UNSUPPORTED_TARGET_COMBINATION", None

            consumer = RecordConsumer()
            try:
                res = consumer.process_record(payload)
                result_ref = res.get("export_row_id") or res.get("item_id") or item_id
                return True, str(result_ref), res
            except Exception as exc:
                logger.error(f"CONSUMER_ERROR: RecordConsumer failed for item {item_id}: {exc}")
                return False, f"RECORD_CONSUMER_FAILED: {exc}", None

        elif item_kind == "agent_task":
            if target_agent != "openclaw":
                logger.error(f"INVALID_ROUTING: agent_task item {item_id} specifies non-openclaw target '{target_agent}'")
                return False, "UNSUPPORTED_TARGET_AGENT", None

            if not self.openclaw_gateway_token:
                logger.error(f"FATAL_CONFIG_ERROR: OPENCLAW_GATEWAY_TOKEN missing for agent_task item {item_id}")
                raise FatalWorkerError("OPENCLAW_GATEWAY_TOKEN missing for agent_task execution")

            openclaw_config = {
                "agent_id": "cvn-broker",
                "gateway_url": os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789"),
                "maximum_output_tokens": 2000,
            }
            adapter = OpenClawAdapter(openclaw_config, self.openclaw_gateway_token)

            try:
                adapter.validate_task(payload)
                req = adapter.convert_task(payload)
                raw_res = adapter.execute(req)
                validated_res = adapter.validate_response(raw_res)
                return True, f"openclaw_res_{item_id[:8]}", validated_res
            except (GatewayAuthenticationError, GatewayConfigurationError) as gw_fatal:
                logger.error(f"FATAL_GATEWAY_ERROR: OpenClaw credential or endpoint configuration failure for item {item_id}: {gw_fatal}")
                raise FatalWorkerError(f"OpenClaw gateway configuration/auth failure: {gw_fatal}") from gw_fatal
            except (UnsupportedTargetAgent, UnsupportedContractVersion, UnsupportedTaskType, InvalidTaskPayload) as client_err:
                logger.error(f"PERMANENT_CONTRACT_ERROR: OpenClaw task validation failed for item {item_id}: {client_err}")
                return False, f"PERMANENT_CONTRACT_ERROR: {client_err}", None
            except (ExecutionTimeoutUnknown, InvalidAgentResponse) as unk_err:
                logger.error(f"EXECUTION_OUTCOME_UNKNOWN: OpenClaw execution outcome unknown for item {item_id}: {unk_err}")
                return False, f"EXECUTION_OUTCOME_UNKNOWN: {unk_err}", None
            except (GatewayUnavailableError, GatewayRateLimitError, GatewayResponseError) as gw_err:
                logger.error(f"GATEWAY_ERROR: OpenClaw execution failed for item {item_id}: {gw_err}")
                return False, f"GATEWAY_ERROR: {gw_err}", None
            except Exception as exc:
                logger.error(f"CONSUMER_ERROR: OpenClaw processing failed for item {item_id}: {exc}")
                return False, f"OPENCLAW_EXECUTION_FAILED: {exc}", None

        else:
            logger.error(f"INVALID_ROUTING: Unsupported item_kind '{item_kind}' for item {item_id}")
            return False, "UNSUPPORTED_ITEM_KIND", None

    def process_item(self, item: Dict[str, Any]) -> bool:
        """Processes a claimed item with journal safety, lease runtime margin checks, and log hygiene."""
        item_id = item.get("item_id", "")
        lease_token = item.get("lease_token", "")
        payload_hash = item.get("payload_hash", "")
        content_hash = item.get("content_hash", "")
        item_kind = item.get("item_kind") or item.get("kind") or ""

        if not item_id or not lease_token:
            logger.error("CLAIM_INVALID: Claimed item missing item_id or lease_token.")
            return False

        logger.info(f"Processing item {item_id} (kind={item_kind})")

        # 1. Validate claimed payload strictly (no payload repairing)
        try:
            validated_payload = self.validate_claimed_item(item)
        except ValueError as val_err:
            logger.error(f"CLAIM_VALIDATION_FAILED: Item {item_id} claim validation error: {val_err}")
            self.fail_item(item_id, lease_token, f"PERMANENT_CLAIM_INVALID: {val_err}", retryable=False)
            return False

        # 2. Record claim in journal with immutable identity check
        try:
            journal_entry = self.journal.record_claim(item_id, payload_hash, content_hash, item_kind)
        except JournalIdentityConflictError as conflict_err:
            logger.error(f"JOURNAL_IDENTITY_CONFLICT: Item {item_id} conflict: {conflict_err}")
            self.fail_item(item_id, lease_token, "JOURNAL_IDENTITY_CONFLICT", retryable=False)
            return False

        # 3. Verify remaining lease duration margin before executing consumer side effect
        lease_expires_at = item.get("lease_expires_at")
        if lease_expires_at is not None:
            remaining_lease = float(lease_expires_at) - time.time()
            if remaining_lease < 30.0:
                logger.error(f"LEASE_EXPIRED_BEFORE_EXECUTION: Item {item_id} remaining lease margin ({remaining_lease:.1f}s) is less than required 30.0s.")
                self.fail_item(item_id, lease_token, f"LEASE_EXPIRED_BEFORE_EXECUTION: remaining {remaining_lease:.1f}s", retryable=True)
                return False

        # 4. Journal recovery check
        result_payload = {
            "status": "delivered",
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "worker_id": self.worker_id,
        }

        if (
            journal_entry
            and journal_entry.get("state") == "consumer_succeeded_pending_remote_complete"
            and journal_entry.get("content_hash") == content_hash
        ):
            logger.info(f"JOURNAL_RECOVERY: Reusing consumer result for item {item_id} and retrying remote completion.")
            res_ref = journal_entry.get("result_reference") or item_id
            result_payload["result_reference"] = res_ref
            return self.complete_item(item_id, lease_token, payload_hash, content_hash, result_payload)

        # 5. Invoke routing consumer
        try:
            success, error_code_or_ref, res_dict = self.route_and_process(item, validated_payload)
        except FatalWorkerError:
            # Fatal gateway auth/config error must propagate to main loop and exit process without modifying remote item
            raise

        if success:
            result_payload["result_reference"] = error_code_or_ref
            if res_dict:
                result_payload["summary"] = res_dict.get("status") or "succeeded"

            # Record consumer success in local journal BEFORE calling Edge complete
            self.journal.record_consumer_success(item_id, error_code_or_ref)

            # Complete remote item
            completed = self.complete_item(item_id, lease_token, payload_hash, content_hash, result_payload)
            return completed
        else:
            self.health_stats.error_count += 1
            if error_code_or_ref.startswith("EXECUTION_OUTCOME_UNKNOWN"):
                logger.error(f"EXECUTION_OUTCOME_UNKNOWN: Item {item_id} transitioning to execution_outcome_unknown journal state to prevent automatic retry.")
                self.journal.record_outcome_unknown(item_id, error_code_or_ref[:50])
                return False

            retryable = True
            if "UNSUPPORTED" in error_code_or_ref or "PERMANENT" in error_code_or_ref or "INVALID" in error_code_or_ref:
                retryable = False

            self.journal.record_failure(item_id, error_code_or_ref[:50])
            self.fail_item(item_id, lease_token, error_code_or_ref[:200], retryable=retryable)
            return False

    def complete_item(
        self,
        item_id: str,
        lease_token: str,
        payload_hash: str,
        content_hash: str,
        result_json: Dict[str, Any],
    ) -> bool:
        """Completes item via Edge complete endpoint."""
        res_ref = result_json.get("result_reference") or item_id
        payload = {
            "item_id": item_id,
            "worker_id": self.worker_id,
            "lease_token": lease_token,
            "payload_hash": payload_hash,
            "content_hash": content_hash,
            "result_reference": str(res_ref),
            "result_json": result_json,
        }

        try:
            status_code, res_json = self._send_edge_rpc("cvn-complete-outbound-item", payload)
            if status_code == 200 and isinstance(res_json, dict) and (res_json.get("completed") or res_json.get("success")):
                logger.info(f"Item {item_id} successfully completed remotely.")
                self.journal.record_remote_complete(item_id)
                self.health_stats.complete_count += 1
                self.health_stats.last_complete_at = time.time()
                return True
            else:
                err_msg = res_json.get("error") if isinstance(res_json, dict) else f"HTTP {status_code}"
                logger.error(f"Edge complete RPC rejected item {item_id}: {err_msg}")
                self.health_stats.error_count += 1
                return False
        except FatalWorkerError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            logger.warning(f"NETWORK_TRANSIENT_ERROR: Complete request failed for item {item_id}: {net_err}")
            self.health_stats.error_count += 1
            return False

    def fail_item(
        self,
        item_id: str,
        lease_token: str,
        failure_reason: str,
        retryable: bool = True,
    ) -> bool:
        """Fails item via Edge failure endpoint."""
        payload = {
            "item_id": item_id,
            "worker_id": self.worker_id,
            "lease_token": lease_token,
            "failure_reason": failure_reason,
            "retryable": retryable,
        }

        try:
            status_code, res_json = self._send_edge_rpc("cvn-fail-outbound-item", payload)
            if status_code == 200:
                logger.info(f"Item {item_id} failure recorded remotely (retryable={retryable}).")
                return True
            return False
        except FatalWorkerError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            logger.warning(f"NETWORK_TRANSIENT_ERROR: Fail request failed for item {item_id}: {net_err}")
            return False

    def reconcile_pending_journal_entries(self) -> None:
        """Startup reconciliation check for pending journal entries via cvn-outbound-status RPC."""
        try:
            pending = self.journal.get_pending_entries()
            if not pending:
                return

            logger.info(f"STARTUP_RECONCILIATION: Found {len(pending)} pending journal entries requiring status check.")
            for entry in pending:
                item_id = entry["item_id"]
                state = entry["state"]
                res_ref = entry.get("result_reference") or item_id

                try:
                    status_code, res_json = self._send_edge_rpc("cvn-outbound-status", {"item_id": item_id})
                    if status_code == 200 and isinstance(res_json, dict) and res_json.get("found"):
                        remote_status = res_json.get("status")
                        logger.info(f"STARTUP_RECONCILIATION: Item {item_id} local state '{state}', remote status '{remote_status}'")
                        if remote_status == "completed":
                            self.journal.record_remote_complete(item_id)
                        elif remote_status in ("claimed", "queued", "approved_pending_enqueue") and state == "consumer_succeeded_pending_remote_complete":
                            # Retry completing remote item using recorded result reference
                            result_payload = {
                                "status": "delivered",
                                "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "worker_id": self.worker_id,
                                "result_reference": res_ref,
                            }
                            self.complete_item(item_id, "reconcile_token", entry["payload_hash"], entry["content_hash"], result_payload)
                    else:
                        logger.warning(f"STARTUP_RECONCILIATION: Status check RPC returned {status_code} for item {item_id}")
                except Exception as rec_err:
                    logger.warning(f"STARTUP_RECONCILIATION: Failed checking status for item {item_id}: {rec_err}")
        except Exception as exc:
            logger.warning(f"Startup journal reconciliation check failed: {exc}")

    def periodic_housekeeping(self) -> None:
        """Runs periodic tasks such as journal retention purging."""
        now = time.time()
        if now - self._last_purge_time > 3600.0:  # Purge hourly
            try:
                self.journal.purge_expired()
            except Exception as exc:
                logger.warning(f"Journal purge failed: {exc}")
            self._last_purge_time = now

    def run(self, single_run: bool = False) -> int:
        """Main worker loop."""
        logger.info(f"Starting OutboundWorkerV2 daemon (worker_id={self.worker_id}, single_run={single_run})")

        # Initial journal purge & startup reconciliation
        try:
            self.journal.purge_expired()
            self.reconcile_pending_journal_entries()
        except Exception as exc:
            logger.warning(f"Startup housekeeping failed: {exc}")

        if not single_run:
            try:
                signal.signal(signal.SIGINT, self.stop)
                signal.signal(signal.SIGTERM, self.stop)
            except (ValueError, AttributeError):
                pass  # Signal binding may fail when called from sub-threads in tests

        processed_count = 0
        while self.running:
            try:
                self.periodic_housekeeping()
                item = self.claim_item()
                if item:
                    if self.process_item(item):
                        processed_count += 1
                else:
                    if single_run:
                        break
                    time.sleep(self.poll_interval)
                if single_run:
                    break
            except FatalWorkerError as fatal_err:
                logger.error(f"FATAL_WORKER_SHUTDOWN: Stopping worker immediately due to auth/config failure: {fatal_err}")
                if single_run:
                    raise
                sys.exit(EX_CONFIG)
            except Exception as exc:
                logger.error(f"UNHANDLED_WORKER_LOOP_ERROR: {exc}")
                if single_run:
                    break
                time.sleep(self.poll_interval)
        return processed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbound Worker V2 Daemon")
    parser.add_argument("--edge-url", help="CVN Edge Base URL")
    parser.add_argument("--worker-id", help="Worker Identity ID")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()

    try:
        worker = OutboundWorkerV2(
            edge_base_url=args.edge_url,
            worker_id=args.worker_id,
            poll_interval_seconds=args.poll_interval,
        )
        worker.run()
    except FatalWorkerError as fatal_err:
        logger.error(f"Startup failed due to configuration or authentication error: {fatal_err}")
        sys.exit(EX_CONFIG)


if __name__ == "__main__":
    main()
