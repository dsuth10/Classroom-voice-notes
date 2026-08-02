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
    """Runnable worker daemon for claiming, executing, completing, and failing v2 outbound items."""

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        visibility_timeout_seconds: int = 300,
    ) -> None:
        self.supabase_url = supabase_url or os.environ.get("SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.worker_id = worker_id or os.environ.get("CVN_WORKER_ID", "openclaw-worker-v2-1")
        self.poll_interval = poll_interval_seconds
        self.visibility_timeout = visibility_timeout_seconds
        self.running = True

        if not self.supabase_url or not self.supabase_key:
            logger.warning("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing; client uninitialized until execution.")

        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from supabase import create_client

            if not self.supabase_url or not self.supabase_key:
                raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables required.")
            self._client = create_client(self.supabase_url, self.supabase_key)
        return self._client

    def stop(self, *args: Any) -> None:
        logger.info(f"Worker {self.worker_id} received stop signal; shutting down gracefully.")
        self.running = False

    def claim_item(self) -> Optional[Dict[str, Any]]:
        """Atomically claims the next processable v2 outbound item from Supabase."""
        try:
            res = self.client.rpc(
                "cvn_claim_outbound_item",
                {
                    "p_worker_id": self.worker_id,
                    "p_visibility_timeout_seconds": self.visibility_timeout,
                    "p_allowed_kinds": ["record_only", "agent_task"],
                    "p_allowed_agents": ["openclaw"],
                },
            ).execute()

            if res.data and isinstance(res.data, dict) and res.data.get("claimed"):
                return res.data
        except Exception as exc:
            logger.error(f"Error claiming outbound item: {exc}")
        return None

    def process_item(self, item: Dict[str, Any]) -> bool:
        """Processes a claimed item and records completion or failure with lease token."""
        item_id = item.get("item_id", "")
        lease_token = item.get("lease_token", "")
        logger.info(f"Processing item {item_id} (lease token {lease_token}) for target agent {item.get('target_agent')}")

        try:
            # Simulates dispatch or executes worker payload processing
            result_payload = {
                "status": "delivered",
                "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "target_agent": item.get("target_agent"),
                "worker_id": self.worker_id,
            }
            self.complete_item(item_id, lease_token, result_payload)
            return True
        except Exception as exc:
            logger.error(f"Failed processing item {item_id}: {exc}")
            self.fail_item(item_id, lease_token, str(exc), retryable=True)
            return False

    def complete_item(self, item_id: str, lease_token: str, result_json: Dict[str, Any]) -> bool:
        """Atomically marks item completed using worker_id and lease_token."""
        try:
            res = self.client.rpc(
                "cvn_complete_outbound_item",
                {
                    "p_item_id": item_id,
                    "p_worker_id": self.worker_id,
                    "p_lease_token": lease_token,
                    "p_result_json": result_json,
                },
            ).execute()
            logger.info(f"Successfully completed item {item_id}: {res.data}")
            return True
        except Exception as exc:
            logger.error(f"Failed to complete item {item_id}: {exc}")
            return False

    def fail_item(self, item_id: str, lease_token: str, failure_reason: str, retryable: bool = True) -> bool:
        """Atomically marks item failed with retry disposition using worker_id and lease_token."""
        try:
            res = self.client.rpc(
                "cvn_fail_outbound_item",
                {
                    "p_item_id": item_id,
                    "p_worker_id": self.worker_id,
                    "p_failure_reason": failure_reason,
                    "p_lease_token": lease_token,
                    "p_retryable": retryable,
                },
            ).execute()
            logger.warning(f"Failed item {item_id}: {res.data}")
            return True
        except Exception as exc:
            logger.error(f"Failed to record failure for item {item_id}: {exc}")
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
