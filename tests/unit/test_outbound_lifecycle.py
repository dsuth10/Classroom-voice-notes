import json
from pathlib import Path

import pytest

from app.destinations.external_outbox import ExternalOutbox
from app.destinations.outbound_lifecycle import (
    UnsafeLifecycleValue,
    parse_openclaw_outcome,
    project_lifecycle_to_note,
)


def _enqueue(outbox: ExternalOutbox, note_path: Path) -> int:
    return outbox.enqueue(
        task_id="CVNI-20260824-LIFECYCLE",
        endpoint_url=(
            "https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/"
            "cvn-submit-outbound-item"
        ),
        payload_json=json.dumps(
            {
                "item_id": "CVNI-20260824-LIFECYCLE",
                "task": {"instructions": "email body must stay out of telemetry"},
            }
        ),
        payload_hash="a" * 64,
        idempotency_key="idem-lifecycle",
        nonce="nonce-lifecycle",
        schema_version="cvn.outbound_item.v2",
        note_path=str(note_path),
        target_agent="openclaw",
    )


def test_openclaw_safe_receipt_and_blocked_contract() -> None:
    completed = parse_openclaw_outcome(
        "ACTION_COMPLETED: receipt_type=agentmail_message_id; receipt_id=msg_abc-123"
    )
    assert completed.state == "completed"
    assert completed.result_reference == "agentmail_message_id:msg_abc-123"

    blocked = parse_openclaw_outcome(
        "ACTION_BLOCKED: reason_code=AGENTMAIL_UNAVAILABLE"
    )
    assert blocked.state == "blocked"
    assert blocked.reason_code == "AGENTMAIL_UNAVAILABLE"


@pytest.mark.parametrize(
    "raw_output",
    [
        "Email sent to teacher@example.com with body hello class",
        "ACTION_COMPLETED: receipt_type=agentmail_message_id; receipt_id=msg 123",
        "ACTION_COMPLETED: receipt_type=agentmail_message_id; receipt_id=msg_123\nbody",
    ],
)
def test_openclaw_contract_rejects_content_bearing_output(raw_output: str) -> None:
    with pytest.raises(UnsafeLifecycleValue):
        parse_openclaw_outcome(raw_output)


def test_lifecycle_is_monotonic_idempotent_and_content_free(tmp_path: Path) -> None:
    note_path = tmp_path / "origin.md"
    note_path.write_text("---\ntitle: Test\n---\nOriginal note body", encoding="utf-8")
    outbox = ExternalOutbox(tmp_path / "outbox.db")
    local_id = _enqueue(outbox, note_path)

    outbox.mark_sent(local_id, "broker-item-id")
    submitted = outbox.get_by_task_id("CVNI-20260824-LIFECYCLE")
    assert submitted is not None
    assert submitted["lifecycle_state"] == "submitted"
    assert submitted["submitted_at"]

    claimed_data = {
        "found": True,
        "item_id": "CVNI-20260824-LIFECYCLE",
        "status": "claimed",
        "created_at": "2026-08-24T08:00:00+00:00",
        "claimed_at": "2026-08-24T08:00:02+00:00",
    }
    claimed = outbox.apply_remote_lifecycle(
        "CVNI-20260824-LIFECYCLE", claimed_data
    )
    assert claimed is not None
    assert claimed["lifecycle_state"] == "claimed"

    completed_data = {
        "found": True,
        "item_id": "CVNI-20260824-LIFECYCLE",
        "status": "completed",
        "created_at": "2026-08-24T08:00:00+00:00",
        "claimed_at": "2026-08-24T08:00:02+00:00",
        "completed_at": "2026-08-24T08:00:04+00:00",
        "result_reference": "agentmail_message_id:msg_abc-123",
        "result_summary": "RAW EMAIL BODY MUST NEVER APPEAR",
    }
    completed = outbox.apply_remote_lifecycle(
        "CVNI-20260824-LIFECYCLE", completed_data
    )
    duplicate = outbox.apply_remote_lifecycle(
        "CVNI-20260824-LIFECYCLE", completed_data
    )
    assert completed is not None
    assert duplicate is not None
    for field in (
        "lifecycle_state",
        "submitted_at",
        "claimed_at",
        "completed_at",
        "safe_receipt",
    ):
        assert duplicate[field] == completed[field]
    assert completed["lifecycle_state"] == "completed"
    assert completed["claimed_at"] == "2026-08-24T08:00:02+00:00"
    assert completed["safe_receipt"] == "agentmail_message_id:msg_abc-123"

    lifecycle_rows = json.dumps(outbox.get_lifecycle_tasks())
    assert "RAW EMAIL BODY" not in lifecycle_rows
    assert "email body must stay out of telemetry" not in lifecycle_rows

    assert project_lifecycle_to_note(
        note_path,
        item_id="CVNI-20260824-LIFECYCLE",
        state="completed",
        submitted_at=completed["submitted_at"],
        claimed_at=completed["claimed_at"],
        completed_at=completed["completed_at"],
        safe_receipt=completed["safe_receipt"],
    )
    assert project_lifecycle_to_note(
        note_path,
        item_id="CVNI-20260824-LIFECYCLE",
        state="completed",
        submitted_at=completed["submitted_at"],
        claimed_at=completed["claimed_at"],
        completed_at=completed["completed_at"],
        safe_receipt=completed["safe_receipt"],
    )

    note_content = note_path.read_text(encoding="utf-8")
    assert note_content.count("<!-- CVN-OUTBOUND-LIFECYCLE:START -->") == 1
    assert 'external_state: "Completed"' in note_content
    assert "- **Submitted:**" in note_content
    assert "- **Claimed:** 2026-08-24T08:00:02+00:00" in note_content
    assert "- **Completed:** 2026-08-24T08:00:04+00:00" in note_content
    assert "agentmail_message_id:msg_abc-123" in note_content
    assert "RAW EMAIL BODY" not in note_content


def test_blocked_state_stores_only_reason_code(tmp_path: Path) -> None:
    note_path = tmp_path / "blocked.md"
    note_path.write_text("Blocked task", encoding="utf-8")
    outbox = ExternalOutbox(tmp_path / "blocked.db")
    local_id = _enqueue(outbox, note_path)
    outbox.mark_sent(local_id, "broker-item-id")

    blocked = outbox.apply_remote_lifecycle(
        "CVNI-20260824-LIFECYCLE",
        {
            "item_id": "CVNI-20260824-LIFECYCLE",
            "status": "dead_letter",
            "failed_at": "2026-08-24T08:01:00+00:00",
            "failure_reason": "recipient@example.com and raw email body",
        },
    )
    assert blocked is not None
    assert blocked["lifecycle_state"] == "blocked"
    assert blocked["blocked_reason"] == "ACTION_BLOCKED"
    assert "recipient@example.com" not in json.dumps(outbox.get_lifecycle_tasks())


def test_status_identity_conflict_is_rejected(tmp_path: Path) -> None:
    note_path = tmp_path / "identity.md"
    note_path.write_text("Identity task", encoding="utf-8")
    outbox = ExternalOutbox(tmp_path / "identity.db")
    local_id = _enqueue(outbox, note_path)
    outbox.mark_sent(local_id, "broker-item-id")

    with pytest.raises(ValueError, match="ERR_STATUS_IDENTITY_CONFLICT"):
        outbox.apply_remote_lifecycle(
            "CVNI-20260824-LIFECYCLE",
            {"item_id": "CVNI-DIFFERENT", "status": "completed"},
        )
