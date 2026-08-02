"""RFC 8785 Canonical JSON Scheme & Outbound Content Hashing for Python."""

import hashlib
import json
from typing import Any, Dict, Optional, Tuple


def _normalize_value(val: Any) -> Any:
    """Recursively normalizes Python objects for canonical JSON formatting:
    - Object keys are sorted.
    - Whole-number floats (e.g. 1.0) are converted to int (1) to match JS JSON.stringify.
    - None inside content/task dicts is preserved.
    """
    if val is None or isinstance(val, (bool, str, int)):
        return val
    if isinstance(val, float):
        if val.is_integer():
            return int(val)
        return val
    if isinstance(val, list):
        return [_normalize_value(item) for item in val]
    if isinstance(val, dict):
        sorted_keys = sorted(val.keys())
        return {k: _normalize_value(val[k]) for k in sorted_keys}
    return val


def build_canonical_object(
    item_kind: str,
    target_agent: Optional[str],
    content: Optional[Dict[str, Any]],
    task: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constructs the canonical v2 object matching TypeScript buildCanonicalObject."""
    return {
        "content": _normalize_value(content or {}),
        "item_kind": item_kind or "record_only",
        "target_agent": target_agent or "",
        "task": _normalize_value(task or {}),
    }


def canonicalize_json(obj: Any) -> str:
    """Serializes object to RFC 8785 canonical JSON string with sorted keys and no unnecessary whitespace."""
    normalized = _normalize_value(obj)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


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
