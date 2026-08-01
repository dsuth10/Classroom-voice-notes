"""Outbound Submission Service - Enqueues approved review items to the local outbox."""

import json
import sqlite3
from typing import Any, Dict, Optional

from app.audit.audit_logger import log_audit_event
from app.config.settings import SettingsManager
from app.destinations.external_outbox import ExternalOutbox
from app.destinations.outbound_payload_builder import (
    build_outbound_payload_v2,
    refresh_transport_signature,
)
from app.destinations.outbound_review_store import (
    OutboundReviewStore,
    compute_content_hash,
)


class OutboundSubmissionService:
    def __init__(
        self,
        settings_manager: Optional[SettingsManager] = None,
        review_store: Optional[OutboundReviewStore] = None,
        outbox: Optional[ExternalOutbox] = None,
    ) -> None:
        self.settings_manager = settings_manager or SettingsManager()
        self.review_store = review_store or OutboundReviewStore()
        self.outbox = outbox or ExternalOutbox()

    def submit_approved_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Processes an approved review item, verifies content hash, builds payload, and enqueues to outbox."""
        item = self.review_store.get_by_id(item_id)
        if not item:
            raise ValueError(f"Review item not found: {item_id}")

        current_status = item["status"]
        if current_status not in ("approved_pending_enqueue", "enqueue_failed"):
            raise ValueError(
                f"Item '{item_id}' cannot be enqueued; current status is '{current_status}'"
            )

        try:
            draft_dict = json.loads(item["draft_json"])
            item_kind = item["item_kind"]
            target_agent = item["target_agent"] or "openclaw"
            content = draft_dict.get("content", {})
            task = draft_dict.get("task")

            # 1. Content Hash Verification
            current_content_hash = compute_content_hash(
                item_kind, target_agent, content, task
            )
            approved_content_hash = item.get("approved_content_hash") or current_content_hash

            if current_content_hash != approved_content_hash:
                raise ValueError(
                    f"Content hash mismatch for item '{item_id}': approved hash "
                    f"'{approved_content_hash}' does not match current hash '{current_content_hash}'."
                )

            # 2. Extract assessment data
            assessment_json = item.get("assessment_json", "{}")
            assessment_dict = json.loads(assessment_json) if assessment_json else {}

            source_device_id = self.settings_manager.get(
                "external_agent.source_device_id", "local_device"
            )
            endpoint_url = self.settings_manager.get(
                "external_agent.endpoint_url", "https://api.supabase.co"
            )
            hmac_secret = self.settings_manager.get("external_agent.hmac_secret", "")

            # 3. Build v2 payload structure
            payload, payload_str, payload_hash = build_outbound_payload_v2(
                item_id=item_id,
                source_device_id=source_device_id,
                item_kind=item_kind,
                target_agent=target_agent,
                content=content,
                automatic_classification=assessment_dict.get(
                    "automatic_classification", "non_sensitive"
                ),
                risk_level=assessment_dict.get("risk_level", "low"),
                findings=assessment_dict.get("findings", []),
                release_basis="human_approval",
                approval_metadata={
                    "approved_at": item.get("approved_at"),
                    "approved_content_hash": approved_content_hash,
                    "reviewer_type": "local_user",
                },
                task=task,
            )

            if hmac_secret:
                _, payload_str, payload_hash, _ = refresh_transport_signature(
                    payload, hmac_secret
                )

            # 4. Enqueue to durable local Outbox (or reuse existing entry if reconciling)
            existing_outbox = self.outbox.get_by_task_id(item_id)
            if existing_outbox:
                local_id = int(existing_outbox["local_id"])
            else:
                local_id = self.outbox.enqueue(
                    task_id=item_id,
                    endpoint_url=endpoint_url,
                    payload_json=payload_str,
                    payload_hash=payload_hash,
                    idempotency_key=payload["idempotency_key"],
                    nonce=payload["nonce"],
                    note_path=item.get("note_path"),
                    target_agent=target_agent,
                )

            # 5. Atomically transition review store status to 'queued'
            updated_item = self.review_store.mark_queued(
                item_id, outbox_local_id=local_id
            )
            log_audit_event(
                "OUTBOUND_SUBMITTED_TO_OUTBOX",
                "submission_service",
                f"Item {item_id} successfully enqueued to outbox (local_id: {local_id}).",
            )
            return updated_item

        except Exception as exc:
            error_msg = f"Outbox enqueue failed: {exc}"
            self.review_store.mark_enqueue_failed(item_id, last_error=error_msg)
            log_audit_event(
                "OUTBOUND_ENQUEUE_FAILED",
                "submission_service",
                f"Item {item_id} enqueue failed: {exc}",
            )
            raise

    def reconcile_pending_enqueues(self) -> int:
        """Recovers any items stuck in approved_pending_enqueue or enqueue_failed."""
        count = 0
        with sqlite3.connect(self.review_store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT item_id FROM review_items WHERE status IN ('approved_pending_enqueue', 'enqueue_failed')"
            )
            item_ids = [row["item_id"] for row in cursor.fetchall()]

        for item_id in item_ids:
            try:
                self.submit_approved_item(item_id)
                count += 1
            except Exception as e:
                log_audit_event(
                    "OUTBOUND_RECONCILE_ERROR",
                    "submission_service",
                    f"Failed to reconcile item {item_id}: {e}",
                )
        return count
