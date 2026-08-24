"""Privacy-safe outbound lifecycle and Obsidian projection helpers.

Only lifecycle metadata, timestamps, safe receipt identifiers and bounded reason
codes belong in this module. Task content and agent response prose are
deliberately excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Optional


LIFECYCLE_STATES = {"submitted", "claimed", "completed", "blocked"}
TERMINAL_LIFECYCLE_STATES = {"completed", "blocked"}

_SAFE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_SAFE_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_:-]{1,95}$")
_SAFE_CANARY_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{2,127}$")
_COMPLETED_RE = re.compile(
    r"^ACTION_COMPLETED: receipt_type=([a-z][a-z0-9_]{1,47}); "
    r"receipt_id=([A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255})$"
)
_BLOCKED_RE = re.compile(r"^ACTION_BLOCKED: reason_code=([A-Z][A-Z0-9_:-]{1,95})$")
_UNKNOWN_RE = re.compile(r"^ACTION_UNKNOWN: reason_code=([A-Z][A-Z0-9_:-]{1,95})$")


class UnsafeLifecycleValue(ValueError):
    """Raised when a value is not safe to persist or project."""


@dataclass(frozen=True)
class AgentOutcome:
    state: str
    result_reference: Optional[str] = None
    reason_code: Optional[str] = None


def build_safe_receipt(receipt_type: str, receipt_id: str) -> str:
    """Build a bounded receipt reference containing identifiers only."""
    if not _SAFE_TYPE_RE.fullmatch(receipt_type):
        raise UnsafeLifecycleValue("unsafe_receipt_type")
    if not _SAFE_ID_RE.fullmatch(receipt_id):
        raise UnsafeLifecycleValue("unsafe_receipt_id")
    value = f"{receipt_type}:{receipt_id}"
    if len(value) > 256:
        raise UnsafeLifecycleValue("safe_receipt_too_long")
    return value


def sanitise_result_reference(value: Any) -> Optional[str]:
    """Accept only the canonical ``type:id`` safe-receipt form."""
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate or len(candidate) > 256 or any(ch.isspace() for ch in candidate):
        return None
    receipt_type, separator, receipt_id = candidate.partition(":")
    if not separator:
        return None
    try:
        return build_safe_receipt(receipt_type, receipt_id)
    except UnsafeLifecycleValue:
        return None


def sanitise_reason_code(value: Any, default: str = "ACTION_BLOCKED") -> str:
    """Reduce failure information to a non-sensitive machine reason code."""
    tokens = str(value or "").strip().split(maxsplit=1)
    if not tokens:
        return default
    candidate = tokens[0].rstrip(":")
    if _SAFE_REASON_RE.fullmatch(candidate):
        return candidate
    return default


def sanitise_timestamp(value: Any) -> Optional[str]:
    """Return a valid ISO-8601 timestamp, or ``None``."""
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate or len(candidate) > 64:
        return None
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    return candidate


def parse_openclaw_outcome(output_text: str) -> AgentOutcome:
    """Parse the strict, privacy-safe OpenClaw completion contract.

    Free-form agent output is never returned to callers. A constrained uppercase
    token remains supported for exact synthetic canary responses.
    """
    candidate = output_text.strip()
    if not candidate or "\n" in candidate or "\r" in candidate:
        raise UnsafeLifecycleValue("agent_outcome_contract_mismatch")

    completed_match = _COMPLETED_RE.fullmatch(candidate)
    if completed_match:
        return AgentOutcome(
            state="completed",
            result_reference=build_safe_receipt(
                completed_match.group(1), completed_match.group(2)
            ),
        )

    blocked_match = _BLOCKED_RE.fullmatch(candidate)
    if blocked_match:
        return AgentOutcome(state="blocked", reason_code=blocked_match.group(1))

    unknown_match = _UNKNOWN_RE.fullmatch(candidate)
    if unknown_match:
        return AgentOutcome(state="unknown", reason_code=unknown_match.group(1))

    if _SAFE_CANARY_RE.fullmatch(candidate):
        return AgentOutcome(
            state="completed",
            result_reference=build_safe_receipt("openclaw_result", candidate),
        )

    raise UnsafeLifecycleValue("agent_outcome_contract_mismatch")


def display_state(state: str) -> str:
    if state not in LIFECYCLE_STATES:
        raise UnsafeLifecycleValue("unknown_lifecycle_state")
    return state.capitalize()


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _upsert_frontmatter(content: str, updates: Mapping[str, Optional[str]]) -> str:
    normalised = content.replace("\r\n", "\n")
    body = "\n" + normalised
    frontmatter_lines: list[str] = []
    if normalised.startswith("---\n"):
        closing_index = normalised.find("\n---", 4)
        if closing_index >= 0:
            frontmatter_lines = normalised[4:closing_index].splitlines()
            body = normalised[closing_index + 4 :]

    update_keys = set(updates)
    retained = [
        line
        for line in frontmatter_lines
        if not any(re.match(rf"^{re.escape(key)}\s*:", line) for key in update_keys)
    ]
    for key, value in updates.items():
        if value is not None:
            retained.append(f"{key}: {_yaml_scalar(value)}")
    return "---\n" + "\n".join(retained) + "\n---" + body


def _lifecycle_block(
    *,
    item_id: str,
    state: str,
    submitted_at: Optional[str],
    claimed_at: Optional[str],
    completed_at: Optional[str],
    blocked_at: Optional[str],
    safe_receipt: Optional[str],
    blocked_reason: Optional[str],
) -> str:
    lines = [
        "<!-- CVN-OUTBOUND-LIFECYCLE:START -->",
        "## Outbound lifecycle",
        "",
        f"- **Task ID:** `{item_id}`",
        f"- **Current state:** {display_state(state)}",
    ]
    if submitted_at:
        lines.append(f"- **Submitted:** {submitted_at}")
    if claimed_at:
        lines.append(f"- **Claimed:** {claimed_at}")
    if completed_at:
        lines.append(f"- **Completed:** {completed_at}")
    if blocked_at:
        lines.append(f"- **Blocked:** {blocked_at}")
    if safe_receipt:
        lines.append(f"- **Safe receipt:** `{safe_receipt}`")
    if blocked_reason:
        lines.append(f"- **Blocked reason:** `{blocked_reason}`")
    lines.append("<!-- CVN-OUTBOUND-LIFECYCLE:END -->")
    return "\n".join(lines)


def project_lifecycle_to_note(
    note_path: str | Path,
    *,
    item_id: str,
    state: str,
    submitted_at: Any = None,
    claimed_at: Any = None,
    completed_at: Any = None,
    blocked_at: Any = None,
    safe_receipt: Any = None,
    blocked_reason: Any = None,
) -> bool:
    """Project lifecycle-only metadata into the originating Obsidian note."""
    path = Path(note_path)
    if not path.is_file() or not _SAFE_ID_RE.fullmatch(item_id):
        return False
    if state not in LIFECYCLE_STATES:
        raise UnsafeLifecycleValue("unknown_lifecycle_state")

    timestamps = {
        "submitted_at": sanitise_timestamp(submitted_at),
        "claimed_at": sanitise_timestamp(claimed_at),
        "completed_at": sanitise_timestamp(completed_at),
        "blocked_at": sanitise_timestamp(blocked_at),
    }
    receipt = sanitise_result_reference(safe_receipt)
    reason = sanitise_reason_code(blocked_reason) if blocked_reason else None

    content = path.read_text(encoding="utf-8")
    updates = {
        "external_item_id": item_id,
        "external_state": display_state(state),
        "external_submitted_at": timestamps["submitted_at"],
        "external_claimed_at": timestamps["claimed_at"],
        "external_completed_at": timestamps["completed_at"],
        "external_blocked_at": timestamps["blocked_at"],
        "external_receipt": receipt,
        "external_blocked_reason": reason,
    }
    updated = _upsert_frontmatter(content, updates)
    block = _lifecycle_block(
        item_id=item_id,
        state=state,
        submitted_at=timestamps["submitted_at"],
        claimed_at=timestamps["claimed_at"],
        completed_at=timestamps["completed_at"],
        blocked_at=timestamps["blocked_at"],
        safe_receipt=receipt,
        blocked_reason=reason,
    )
    marker_pattern = re.compile(
        r"<!-- CVN-OUTBOUND-LIFECYCLE:START -->.*?"
        r"<!-- CVN-OUTBOUND-LIFECYCLE:END -->",
        re.DOTALL,
    )
    if marker_pattern.search(updated):
        updated = marker_pattern.sub(lambda _match: block, updated)
    else:
        updated = updated.rstrip() + "\n\n" + block + "\n"

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.close(fd)
        Path(temp_name).write_text(updated, encoding="utf-8")
        os.replace(temp_name, path)
    finally:
        temp_path = Path(temp_name)
        if temp_path.exists():
            temp_path.unlink()
    return True
