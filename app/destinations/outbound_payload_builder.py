"""Outbound Payload Builder v2 - Constructs cvn.outbound_item.v2 envelopes."""

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import uuid

from app.destinations.outbound_review_store import compute_content_hash


def build_outbound_payload_v2(
    item_id: str,
    source_device_id: str,
    item_kind: str,
    target_agent: str,
    content: Dict[str, Any],
    automatic_classification: str = "non_sensitive",
    risk_level: str = "low",
    findings: Optional[List[str]] = None,
    release_basis: str = "human_approval",
    approval_metadata: Optional[Dict[str, Any]] = None,
    task: Optional[Dict[str, Any]] = None,
    policy_gate_version: str = "2.0.0",
    now_provider: Optional[Callable[[], datetime]] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """Constructs a cvn.outbound_item.v2 payload dictionary and its deterministic serialisation.

    Returns:
        (payload_dict, deterministic_json_str, payload_hash)
    """
    if now_provider is not None:
        now = now_provider()
    else:
        now = datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("now_provider must return a timezone-aware UTC datetime")

    now_iso = now.isoformat()
    idempotency_key = str(uuid.uuid4())
    nonce = str(uuid.uuid4())

    content_hash = compute_content_hash(item_kind, target_agent, content, task)

    privacy_block: Dict[str, Any] = {
        "automatic_classification": automatic_classification,
        "risk_level": risk_level,
        "findings": findings or [],
        "policy_gate_version": policy_gate_version,
        "release_basis": release_basis,
    }

    if release_basis == "human_approval" or approval_metadata:
        app_meta = approval_metadata or {}
        privacy_block["approval"] = {
            "approved_at": app_meta.get("approved_at", now_iso),
            "approved_content_hash": app_meta.get(
                "approved_content_hash", content_hash
            ),
            "reviewer_type": app_meta.get("reviewer_type", "local_user"),
        }

    payload = {
        "schema_version": "cvn.outbound_item.v2",
        "item_id": item_id,
        "created_at": now_iso,
        "source": "classroom_voice_notes",
        "source_device_id": source_device_id,
        "item_kind": item_kind,
        "target_agent": target_agent,
        "content": content,
        "privacy": privacy_block,
        "task": task if item_kind == "agent_task" else None,
        "content_hash": content_hash,
        "signed_at": now_iso,
        "nonce": nonce,
        "idempotency_key": idempotency_key,
    }

    deterministic_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    payload_hash = hashlib.sha256(
        deterministic_json.encode("utf-8")
    ).hexdigest()

    return payload, deterministic_json, payload_hash


def refresh_transport_signature(
    payload_input: Union[Dict[str, Any], str],
    hmac_secret: str,
    now_provider: Optional[Callable[[], datetime]] = None,
) -> Tuple[Dict[str, Any], str, str, str]:
    """Rebuilds payload transport envelope with fresh signed_at and nonce while maintaining item_id & content_hash.

    Returns:
        (refreshed_payload_dict, deterministic_json_str, payload_hash, signature_hex)
    """
    if isinstance(payload_input, str):
        payload_dict = json.loads(payload_input)
    else:
        payload_dict = dict(payload_input)

    refreshed = dict(payload_dict)
    if now_provider is not None:
        now_dt = now_provider()
    else:
        now_dt = datetime.now(timezone.utc)

    if now_dt.tzinfo is None:
        raise ValueError("now_provider must return a timezone-aware UTC datetime")

    now_iso = now_dt.isoformat()
    refreshed["signed_at"] = now_iso
    refreshed["nonce"] = str(uuid.uuid4())

    deterministic_json = json.dumps(
        refreshed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    payload_hash = hashlib.sha256(
        deterministic_json.encode("utf-8")
    ).hexdigest()
    signature = hmac.new(
        hmac_secret.encode("utf-8"),
        deterministic_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return refreshed, deterministic_json, payload_hash, signature
