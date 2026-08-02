"""Unit tests for PR 10 startup recovery, remote status reconciliation, and automatic retention purging."""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.destinations.outbound_review_store import OutboundReviewStore
from app.destinations.outbound_submission_service import OutboundSubmissionService


def test_startup_recovery_and_remote_status_reconciliation(tmp_path: Path) -> None:
    """Verifies startup recovery workflow, pending enqueue recovery, and remote status reconciliation."""
    db_file = tmp_path / "test_recovery_pr10.db"
    store = OutboundReviewStore(db_file)

    # 1. Create a stuck pending item
    store.create_review_item(
        item_id="CVNI-REC-1",
        note_path="/notes/lesson.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Pending Item"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
        status="approved_pending_enqueue",
    )

    # 2. Create a queued item whose remote status is completed
    store.create_review_item(
        item_id="CVNI-REC-2",
        note_path="/notes/remote.md",
        item_kind="record_only",
        target_agent="openclaw",
        draft_json=json.dumps({"content": {"title": "Remote Completed"}}),
        assessment_json=json.dumps({"risk_level": "low"}),
        status="queued",
    )

    mock_outbox = MagicMock()
    mock_outbox.get_by_task_id.return_value = {"local_id": 42}
    mock_outbox.enqueue.return_value = 42

    service = OutboundSubmissionService(review_store=store, outbox=mock_outbox)

    mock_client = MagicMock()
    mock_rpc = MagicMock()
    rpc_response = MagicMock()
    rpc_response.data = {"found": True, "item_id": "CVNI-REC-2", "status": "completed"}
    mock_rpc.execute.return_value = rpc_response
    mock_client.rpc.return_value = mock_rpc

    summary = service.run_startup_recovery(broker_client=mock_client)
    assert summary["re_enqueued"] == 1
    assert summary["reconciled_remote"] == 2

    item2 = store.get_by_id("CVNI-REC-2")
    assert item2 is not None
    assert item2["status"] == "sent"

