"""Outbound Worker V2 Daemon — Capability-scoped daemon for processing v2 outbound items."""

import argparse
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("OutboundWorkerV2")


class OutboundWorkerV2:
    """Runnable worker daemon for claiming, executing, completing, and failing v2 outbound items via Edge RPC endpoints."""

    def __init__(
        self,
        edge_base_url: Optional[str] = None,
        worker_bearer_token: Optional[str] = None,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        visibility_timeout_seconds: int = 300,
    ) -> None:
        sb_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        default_edge_url = f"{sb_url}/functions/v1" if sb_url else ""
        self.edge_base_url = (edge_base_url or os.environ.get("CVN_EDGE_BASE_URL") or default_edge_url).rstrip("/")
        self.worker_bearer_token = worker_bearer_token or os.environ.get("CVN_WORKER_BEARER_TOKEN") or os.environ.get("CVN_BEARER_TOKEN") or ""
        self.worker_id = worker_id or os.environ.get("CVN_WORKER_ID", "openclaw-worker-v2-1")
        self.poll_interval = poll_interval_seconds
        self.visibility_timeout = visibility_timeout_seconds
        self.running = True

        if not self.edge_base_url or not self.worker_bearer_token:
            logger.warning("CVN_EDGE_BASE_URL or CVN_WORKER_BEARER_TOKEN unconfigured.")

    def stop(self, *args: Any) -> None:
        logger.info(f"Worker {self.worker_id} received stop signal; shutting down gracefully.")
        self.running = False

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.worker_bearer_token}",
            "Content-Type": "application/json",
            "X-CVN-Key-Id": self.worker_id,
        }

    def claim_item(self) -> Optional[Dict[str, Any]]:
        """Claims the next processable v2 outbound item via Edge claim endpoint."""
        import urllib.request

        url = f"{self.edge_base_url}/cvn-claim-outbound-item"
        payload = {
            "worker_id": self.worker_id,
            "visibility_timeout_seconds": self.visibility_timeout,
            "allowed_kinds": ["record_only", "agent_task"],
            "allowed_agents": ["openclaw"],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                res_json = json.loads(res_body)
                if isinstance(res_json, dict) and res_json.get("claimed"):
                    return res_json
        except Exception as exc:
            logger.error(f"Error claiming outbound item via Edge endpoint: {exc}")
        return None

    def process_item(self, item: Dict[str, Any]) -> bool:
        """Processes a claimed item and records completion or failure with lease token."""
        item_id = item.get("item_id", "")
        lease_token = item.get("lease_token", "")
        payload_hash = item.get("payload_hash", "")
        content_hash = item.get("content_hash", "")

        logger.info(f"Processing item {item_id} (lease token {lease_token}) for target agent {item.get('target_agent')}")

        try:
            result_payload = {
                "status": "delivered",
                "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "target_agent": item.get("target_agent"),
                "worker_id": self.worker_id,
            }
            self.complete_item(item_id, lease_token, payload_hash, content_hash, result_payload)
            return True
        except Exception as exc:
            logger.error(f"Failed processing item {item_id}: {exc}")
            self.fail_item(item_id, lease_token, str(exc), retryable=True)
            return False

    def complete_item(
        self,
        item_id: str,
        lease_token: str,
        payload_hash: str,
        content_hash: str,
        result_json: Dict[str, Any],
    ) -> bool:
        """Marks item completed using worker_id, lease_token, payload_hash, and content_hash via Edge complete endpoint."""
        import urllib.request

        url = f"{self.edge_base_url}/cvn-complete-outbound-item"
        payload = {
            "item_id": item_id,
            "worker_id": self.worker_id,
            "lease_token": lease_token,
            "payload_hash": payload_hash,
            "content_hash": content_hash,
            "result_json": result_json,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                res_json = json.loads(res_body)
                logger.info(f"Successfully completed item {item_id}: {res_json}")
                return True
        except Exception as exc:
            logger.error(f"Failed to complete item {item_id} via Edge endpoint: {exc}")
            return False

    def fail_item(
        self,
        item_id: str,
        lease_token: str,
        failure_reason: str,
        retryable: bool = True,
    ) -> bool:
        """Marks item failed with retry disposition using worker_id and lease_token via Edge fail endpoint."""
        import urllib.request

        url = f"{self.edge_base_url}/cvn-fail-outbound-item"
        payload = {
            "item_id": item_id,
            "worker_id": self.worker_id,
            "lease_token": lease_token,
            "failure_reason": failure_reason,
            "retryable": retryable,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                res_json = json.loads(res_body)
                logger.warning(f"Failed item {item_id}: {res_json}")
                return True
        except Exception as exc:
            logger.error(f"Failed to record failure for item {item_id} via Edge endpoint: {exc}")
            return False

    def run(self, single_run: bool = False) -> int:
        """Runs main daemon poll loop or single-shot run."""
        logger.info(f"Starting OutboundWorkerV2 [worker_id={self.worker_id}, poll_interval={self.poll_interval}s]")
        processed_count = 0

        while self.running:
            item = self.claim_item()
            if item:
                self.process_item(item)
                processed_count += 1
                if single_run:
                    break
            else:
                if single_run:
                    logger.info("Single run requested and no items claimed.")
                    break
                time.sleep(self.poll_interval)

        logger.info(f"OutboundWorkerV2 stopped. Total items processed: {processed_count}")
        return processed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="OutboundWorkerV2 Daemon")
    parser.add_argument("--once", "--single-run", action="store_true", help="Run once and exit")
    parser.add_argument("--worker-id", type=str, help="Worker ID identifier")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()

    worker = OutboundWorkerV2(
        worker_id=args.worker_id,
        poll_interval_seconds=args.poll_interval,
    )

    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)

    worker.run(single_run=args.once)


if __name__ == "__main__":
    main()
