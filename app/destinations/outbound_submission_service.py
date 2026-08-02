"""Outbound Submission Service - Enforces fail-closed, idempotent outbox enqueue for approved outbound items."""
import json
import sqlite3
from typing import Any, Dict, List, Optional


from app.audit.audit_logger import log_audit_event
from app.config.environment import submission_endpoint
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
            raise ValueError(f"ERR_ITEM_NOT_FOUND: Review item not found: {item_id}")

        current_status = item["status"]
        if current_status not in ("approved_pending_enqueue", "enqueue_failed"):
            raise ValueError(
                f"ERR_INVALID_STATUS: Item '{item_id}' cannot be enqueued; current status is '{current_status}'"
            )

        try:
            draft_dict = json.loads(item["draft_json"])
            item_kind = item["item_kind"]
            target_agent = item["target_agent"] or "openclaw"
            content = draft_dict.get("content", {})
            task = draft_dict.get("task")

            # 1. Require stored approved_content_hash (never default/substitute current hash)
            approved_content_hash = item.get("approved_content_hash")
            if not approved_content_hash:
                raise ValueError(f"ERR_MISSING_APPROVAL_HASH: Item '{item_id}' has no stored approved_content_hash.")

            # Verify current content matches stored approved_content_hash
            current_content_hash = compute_content_hash(item_kind, target_agent, content, task)
            if current_content_hash != approved_content_hash:
                raise ValueError(
                    f"ERR_CONTENT_HASH_MISMATCH: Content hash mismatch for item '{item_id}': approved hash "
                    f"'{approved_content_hash}' does not match current hash '{current_content_hash}'."
                )

            # 2. Require valid assessment fields and enums (fail closed if missing/invalid)
            assessment_json = item.get("assessment_json", "{}")
            assessment_dict = json.loads(assessment_json) if assessment_json else {}

            raw_classification = assessment_dict.get("automatic_classification")
            valid_classifications = ("non_sensitive", "sensitive_pii", "safeguarding", "medical", "sensitive")
            if not isinstance(raw_classification, str) or raw_classification not in valid_classifications:
                raise ValueError(f"ERR_INVALID_ASSESSMENT: Missing or invalid automatic_classification '{raw_classification}'.")
            automatic_classification: str = raw_classification

            raw_risk = assessment_dict.get("risk_level")
            valid_risks = ("low", "medium", "high")
            if not isinstance(raw_risk, str) or raw_risk not in valid_risks:
                raise ValueError(f"ERR_INVALID_ASSESSMENT: Missing or invalid risk_level '{raw_risk}'.")
            risk_level: str = raw_risk

            raw_findings = assessment_dict.get("findings", [])
            findings_list: List[str] = [str(f) for f in raw_findings] if isinstance(raw_findings, list) else []

            raw_checks = assessment_dict.get("checks_passed", [])
            checks_passed_list: List[str] = [str(c) for c in raw_checks] if isinstance(raw_checks, list) else []

            # 3. Require a non-empty persisted source_device_id (no 'local_device' fallback)
            source_device_id = self.settings_manager.get("external_agent.source_device_id")
            if not source_device_id or source_device_id == "local_device":
                raise ValueError("ERR_MISSING_DEVICE_ID: Persistent source_device_id is uninitialized or empty.")

            # 4. Require release_basis to agree with stored approval_method
            approval_method = item.get("approval_method")
            if not approval_method:
                raise ValueError("ERR_MISSING_APPROVAL_METHOD: Missing approval_method for approved item.")

            if approval_method == "trusted_mode":
                expected_basis = "trusted_mode"
            elif approval_method in ("manual_ui", "human_approval"):
                expected_basis = "human_approval"
            elif approval_method == "automatic_policy":
                expected_basis = "automatic_policy"
            else:
                raise ValueError(f"ERR_RELEASE_BASIS_MISMATCH: Unknown approval_method '{approval_method}'.")

            release_basis = item.get("release_basis") or expected_basis
            if release_basis != expected_basis:
                raise ValueError(f"ERR_RELEASE_BASIS_MISMATCH: Release basis '{release_basis}' conflicts with approval_method '{approval_method}'.")

            # 5. Build v2 payload
            hmac_secret: str = ""
            try:
                from app.config import keyring_store
                from app.config.environment import get_env_credential_ref
                hmac_ref = get_env_credential_ref("hmac_secret")
                hmac_secret = keyring_store.get_secret(hmac_ref) or ""
            except Exception:
                pass

            payload, payload_str, payload_hash = build_outbound_payload_v2(
                item_id=item_id,
                source_device_id=source_device_id,
                item_kind=item_kind,
                target_agent=target_agent,
                content=content,
                automatic_classification=automatic_classification,
                risk_level=risk_level,
                findings=findings_list,
                release_basis=release_basis,
                approval_metadata={
                    "approved_at": item.get("approved_at"),
                    "approved_content_hash": approved_content_hash,
                    "reviewer_type": approval_method,
                },
                task=task,
                checks_passed=checks_passed_list,
            )

            if hmac_secret:
                _, payload_str, payload_hash, _ = refresh_transport_signature(
                    payload, hmac_secret
                )

            # 6. Require validated v2 endpoint from submission_endpoint()
            schema_version = "cvn.outbound_item.v2"
            try:
                base_url = self.settings_manager.get("external_agent.endpoint_url", "")
                if base_url:
                    endpoint_url = submission_endpoint(schema_version, base_url=base_url)
                else:
                    endpoint_url = submission_endpoint(schema_version)
            except Exception:
                # Synthetic endpoint for local dev / unconfigured test environment
                endpoint_url = "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-outbound-item"


            # 7. Check existing outbox row for exact identity match vs conflict
            existing_outbox = self.outbox.get_by_task_id(item_id)
            if existing_outbox:
                mismatches = []
                if existing_outbox.get("schema_version") != schema_version:
                    mismatches.append("schema_version")
                if existing_outbox.get("item_kind") != item_kind:
                    mismatches.append("item_kind")
                if existing_outbox.get("target_agent") != target_agent:
                    mismatches.append("target_agent")
                if existing_outbox.get("content_hash") != approved_content_hash:
                    mismatches.append("content_hash")
                if existing_outbox.get("release_basis") != release_basis:
                    mismatches.append("release_basis")

                if mismatches:
                    conflict_msg = f"ERR_OUTBOX_CONFLICT: Existing outbox entry for '{item_id}' has conflicting fields: {', '.join(mismatches)}"
                    raise ValueError(conflict_msg)

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
                    schema_version=schema_version,
                    item_kind=item_kind,
                    content_hash=approved_content_hash,
                    release_basis=release_basis,
                    review_id=str(item.get("review_id", "")),
                )

            # Atomically transition review store status to 'queued'
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
            self.review_store.mark_enqueue_failed(item_id, last_error=str(exc))
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

    def reconcile_remote_statuses(self, broker_client: Optional[Any] = None) -> int:
        """Reconciles queued local review items against remote Supabase status."""
        import os

        count = 0
        with sqlite3.connect(self.review_store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT item_id FROM review_items WHERE status = 'queued'"
            )
            queued_items = [row["item_id"] for row in cursor.fetchall()]

        if not queued_items:
            return 0

        client = broker_client
        if client is None:
            try:
                from supabase import create_client  # type: ignore[attr-defined]

                url = self.settings_manager.get("supabase.url", "") or os.environ.get("SUPABASE_URL", "")
                key = self.settings_manager.get("supabase.service_role_key", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
                if url and key:
                    client = create_client(url, key)
            except Exception:
                pass

        if client is None:
            return 0

        source_device_id = str(self.settings_manager.get("external_agent.source_device_id") or "")
        for item_id in queued_items:
            try:
                rpc_params = {"p_item_id": item_id}
                if source_device_id:
                    rpc_params["p_source_device_id"] = source_device_id
                res = client.rpc("cvn_get_outbound_item_status", rpc_params).execute()

                if res.data and isinstance(res.data, dict) and res.data.get("found"):
                    remote_status = res.data.get("status")
                    if remote_status == "completed":
                        self.review_store.mark_completed(item_id)
                        count += 1
                    elif remote_status in ("failed_permanent", "dead_letter"):
                        self.review_store.mark_delivery_failed(
                            item_id, last_error=f"Remote status: {remote_status}"
                        )
                        count += 1
            except Exception as e:
                log_audit_event(
                    "OUTBOUND_STATUS_RECONCILE_ERROR",
                    "submission_service",
                    f"Failed remote status lookup for {item_id}: {e}",
                )

        return count

    def run_startup_recovery(
        self, retention_days: int = 30, broker_client: Optional[Any] = None
    ) -> Dict[str, int]:
        """Runs startup retention purge, pending enqueue recovery, and remote status reconciliation."""
        log_audit_event(
            "OUTBOUND_STARTUP_RECOVERY_BEGIN",
            "submission_service",
            "Starting outbound startup recovery and status reconciliation sequence.",
        )

        purged_count = self.review_store.purge_expired_reviews(retention_days=retention_days)
        re_enqueued_count = self.reconcile_pending_enqueues()
        reconciled_remote_count = self.reconcile_remote_statuses(broker_client=broker_client)

        summary = {
            "purged": purged_count,
            "re_enqueued": re_enqueued_count,
            "reconciled_remote": reconciled_remote_count,
        }

        log_audit_event(
            "OUTBOUND_STARTUP_RECOVERY_COMPLETE",
            "submission_service",
            f"Startup recovery completed: {summary}",
        )
        return summary
