"""Outbound Routing Service - Central dispatcher for outbound sharing modes."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from pathlib import Path

import secrets
from typing import Any, Dict, Optional

from app.audit.audit_logger import log_audit_event
from app.config.settings import SettingsManager
from app.destinations.outbound_review_store import OutboundReviewStore
from app.ollama_router.policy_gate import PolicyGate
from app.privacy.outbound_assessment import OutboundAssessment


@dataclass(frozen=True)
class OutboundRoutingResult:
    action: str  # "saved_locally_only", "safe_auto_dispatched", "added_to_review_queue", "trusted_auto_queued"
    item_id: Optional[str] = None
    assessment: Optional[OutboundAssessment] = None


class OutboundRoutingService:
    def __init__(
        self,
        settings_manager: SettingsManager,
        policy_gate: Optional[PolicyGate] = None,
        review_store: Optional[OutboundReviewStore] = None,
    ) -> None:
        self.settings_manager = settings_manager
        self.policy_gate = policy_gate or PolicyGate()
        self.review_store = review_store or OutboundReviewStore()

    def generate_item_id(self) -> str:
        now = datetime.now(timezone.utc)
        return (
            "CVNI-"
            + now.strftime("%Y%m%d-%H%M%S")
            + "-"
            + secrets.token_hex(2).upper()
        )

    def handle_capture(
        self,
        classification: Dict[str, Any],
        transcript: str,
        note_path: str,
        recorded_at: str,
        duration_seconds: int,
        safe_task: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> OutboundRoutingResult:
        mode = self.settings_manager.external_sharing_mode()

        if mode == "off":
            log_audit_event(
                "OUTBOUND_ROUTING",
                "routing_service",
                "Sharing mode is 'off'; note retained locally only.",
            )
            return OutboundRoutingResult(action="saved_locally_only")

        category = classification.get("category", "general_note")
        sensitivity = classification.get("sensitivity", "non_sensitive")
        target_agent = self.settings_manager.get(
            "external_agent.target_agent_default", "openclaw"
        )
        endpoint_url = self.settings_manager.get(
            "external_agent.endpoint_url", ""
        )
        source_device_id = self.settings_manager.get(
            "external_agent.source_device_id", "cvn-device"
        )
        vault_path = self.settings_manager.get("obsidian_vault_path", "")
        config = self.settings_manager.get("external_agent", {})

        # Prepare payload and safe_task if not supplied
        if payload is None and category == "agent_task":
            from app.destinations.payload_builder import build_payload

            try:
                policy_gate_ver = config.get("policy_gate_version", "1.0.0")
                payload_dict, _, _ = build_payload(
                    classification_data=classification,
                    source_device_id=source_device_id,
                    target_agent=target_agent,
                    checks_passed=[],
                    policy_gate_version=policy_gate_ver,
                )
                payload = payload_dict
                safe_task = payload.get("task")
            except Exception as e:
                log_audit_event(
                    "OUTBOUND_ROUTING_ERROR",
                    "routing_service",
                    f"Failed to build v1 payload: {e}",
                )

        # Conduct structured outbound privacy assessment
        assessment = self.policy_gate.assess_outbound(
            category=category,
            sensitivity=sensitivity,
            safe_task=safe_task,
            transcript=transcript,
            payload=payload or {},
            source_device_id=source_device_id,
            target_agent=target_agent,
            endpoint_url=endpoint_url,
            vault_path=vault_path,
            config=config,
        )

        if mode == "safe_auto":
            if category == "agent_task" and assessment.safe_auto_allowed:
                from app.destinations.external_agent_dispatcher import (
                    ExternalAgentDispatcher,
                )

                dispatcher = ExternalAgentDispatcher(self.settings_manager)
                dispatched = dispatcher.dispatch(classification, note_path, transcript)
                if dispatched:
                    return OutboundRoutingResult(
                        action="safe_auto_dispatched",
                        assessment=assessment,
                    )
                log_audit_event(
                    "OUTBOUND_ROUTING_DISPATCH_FAILED",
                    "routing_service",
                    "Mode 'safe_auto': dispatcher returned failure; saving locally.",
                )
                return OutboundRoutingResult(
                    action="saved_locally_only",
                    assessment=assessment,
                )
            log_audit_event(
                "OUTBOUND_ROUTING",
                "routing_service",
                "Mode 'safe_auto': item not allowed for automatic dispatch;"
                " saved locally.",
            )
            return OutboundRoutingResult(
                action="saved_locally_only",
                assessment=assessment,
            )

        # For review_all and trusted_auto, construct draft
        item_id = self.generate_item_id()
        include_transcript = self.settings_manager.get(
            "external_agent.include_full_transcript", False
        )
        default_kind = self.settings_manager.get(
            "external_agent.default_item_kind", "record_only"
        )

        structured_fields = classification.get("structured_fields") or classification.get("category_fields") or {}
        content = {
            "title": classification.get("title", "Voice Note Capture"),
            "summary": classification.get("summary", ""),
            "transcript": transcript if include_transcript else None,
            "category": category,
            "tags": classification.get("tags", []),
            "structured_fields": structured_fields,
        }

        task = safe_task if default_kind == "agent_task" else None
        draft_dict = {
            "item_kind": default_kind,
            "target_agent": target_agent,
            "content": content,
            "task": task,
        }

        # Run v2 assessment over draft payload
        v2_assessment = self.policy_gate.assess_v2_item(
            item_kind=default_kind,
            target_agent=target_agent,
            content=content,
            task=task,
            vault_path=vault_path,
            config=config,
        )

        # Merge v2 assessment risk and findings
        risk_rank = {"high": 3, "medium": 2, "low": 1}
        merged_risk = (
            v2_assessment.risk_level
            if risk_rank.get(v2_assessment.risk_level, 1) > risk_rank.get(assessment.risk_level, 1)
            else assessment.risk_level
        )
        merged_findings = sorted(list(set(assessment.findings + v2_assessment.findings)))
        merged_checks = sorted(list(set(assessment.checks_passed + v2_assessment.checks_passed)))
        merged_redactions = sorted(list(set(assessment.suggested_redactions + v2_assessment.suggested_redactions)))

        assessment_dict = {
            "automatic_classification": assessment.automatic_classification,
            "risk_level": merged_risk,
            "findings": merged_findings,
            "checks_passed": merged_checks,
            "suggested_redactions": merged_redactions,
            "safe_auto_allowed": assessment.safe_auto_allowed and v2_assessment.safe_auto_allowed,
        }

        if mode == "review_all":
            self.review_store.create_review_item(
                item_id=item_id,
                note_path=note_path,
                item_kind=default_kind,
                target_agent=target_agent,
                draft_json=json.dumps(draft_dict),
                assessment_json=json.dumps(assessment_dict),
                status="awaiting_review",
            )
            self._update_note_frontmatter(note_path, item_id, "awaiting_review")
            return OutboundRoutingResult(
                action="added_to_review_queue",
                item_id=item_id,
                assessment=assessment,
            )

        if mode == "trusted_auto":
            pause_on_high_risk = self.settings_manager.get(
                "external_agent.trusted_pause_on_high_risk", True
            )
            if merged_risk == "high" and pause_on_high_risk:
                self.review_store.create_review_item(
                    item_id=item_id,
                    note_path=note_path,
                    item_kind=default_kind,
                    target_agent=target_agent,
                    draft_json=json.dumps(draft_dict),
                    assessment_json=json.dumps(assessment_dict),
                    status="awaiting_review",
                )
                self._update_note_frontmatter(
                    note_path, item_id, "awaiting_review"
                )
                log_audit_event(
                    "OUTBOUND_TRUSTED_PAUSED",
                    "routing_service",
                    f"Item {item_id} paused due to high risk finding.",
                )
                return OutboundRoutingResult(
                    action="added_to_review_queue",
                    item_id=item_id,
                    assessment=assessment,
                )

            # Release automatically in trusted mode
            self.review_store.create_review_item(
                item_id=item_id,
                note_path=note_path,
                item_kind=default_kind,
                target_agent=target_agent,
                draft_json=json.dumps(draft_dict),
                assessment_json=json.dumps(assessment_dict),
                status="awaiting_review",
            )
            self.review_store.approve(item_id, approval_method="trusted_mode")
            self._update_note_frontmatter(note_path, item_id, "approved_pending_enqueue")

            # Enqueue via submission service — only report trusted_auto_queued when durable row exists
            try:
                from app.destinations.outbound_submission_service import OutboundSubmissionService
                submission_svc = OutboundSubmissionService(
                    settings_manager=self.settings_manager,
                    review_store=self.review_store,
                )
                submission_svc.submit_approved_item(item_id)
                log_audit_event(
                    "OUTBOUND_TRUSTED_RELEASE",
                    "routing_service",
                    f"Item {item_id} released via trusted_mode and enqueued.",
                )
                return OutboundRoutingResult(
                    action="trusted_auto_queued",
                    item_id=item_id,
                    assessment=assessment,
                )
            except Exception as enqueue_exc:
                log_audit_event(
                    "OUTBOUND_TRUSTED_ENQUEUE_FAILED",
                    "routing_service",
                    f"Item {item_id} trusted_mode approved but enqueue failed: {enqueue_exc}.",
                )
                return OutboundRoutingResult(
                    action="added_to_review_queue",
                    item_id=item_id,
                    assessment=assessment,
                )

        return OutboundRoutingResult(action="saved_locally_only")

    def _update_note_frontmatter(
        self, note_path: str, item_id: str, state: str
    ) -> None:
        """Appends external_item_id and external_state to Obsidian note frontmatter."""
        if not note_path or not Path(note_path).exists():
            return
        try:
            with open(note_path, "r", encoding="utf-8") as f:
                content = f.read()

            new_lines = [
                f"external_item_id: {item_id}",
                f"external_state: {state}",
            ]
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm = parts[1].strip()
                    fm_updated = fm + "\n" + "\n".join(new_lines) + "\n"
                    new_content = f"---\n{fm_updated}---" + parts[2]
                else:
                    new_content = content + "\n\n" + "\n".join(new_lines)
            else:
                new_content = (
                    "---\n" + "\n".join(new_lines) + "\n---\n\n" + content
                )

            with open(note_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            log_audit_event(
                "FRONTMATTER_UPDATE_ERROR",
                "routing_service",
                f"Failed to update frontmatter: {e}",
            )
