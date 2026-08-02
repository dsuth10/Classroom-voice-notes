"""RFC 8785 Canonical JSON Scheme & Outbound Content Hashing for Python."""

import hashlib
import math
from typing import Any, Dict, Optional, Tuple
import rfc8785


def _validate_json_domain(obj: Any) -> None:
    """Rejects unsupported objects, non-string keys, NaN, and +/- Infinity."""
    if obj is None or isinstance(obj, (bool, str, int)):
        return
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(f"Non-finite float value {obj} is outside the RFC 8785 JSON domain.")
        return
    if isinstance(obj, list):
        for item in obj:
            _validate_json_domain(item)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError(f"Dictionary key {k!r} is not a string.")
            _validate_json_domain(v)
        return
    raise TypeError(f"Object of type {type(obj).__name__} is outside the RFC 8785 JSON domain.")


def build_canonical_object(
    item_kind: str,
    target_agent: Optional[str],
    content: Optional[Dict[str, Any]],
    task: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constructs the canonical v2 object matching TypeScript buildCanonicalObject."""
    normalized_content = content if content is not None else {}
    normalized_task = task if task is not None else {}

    _validate_json_domain(normalized_content)
    _validate_json_domain(normalized_task)

    return {
        "content": normalized_content,
        "item_kind": item_kind or "record_only",
        "target_agent": target_agent or "",
        "task": normalized_task,
    }


def canonicalize_json(obj: Any) -> str:
    """Serializes object to RFC 8785 canonical JSON string using rfc8785 package."""
    _validate_json_domain(obj)
    return rfc8785.dumps(obj).decode("utf-8")


def compute_canonical_content_hash(
    item_kind: str,
    target_agent: Optional[str],
    content: Optional[Dict[str, Any]],
    task: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Returns (canonical_json_string, sha256_hex_hash)."""
    canonical_obj = build_canonical_object(item_kind, target_agent, content, task)
    canonical_str = canonicalize_json(canonical_obj)
    digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
    return canonical_str, digest
