"""Unit tests for OutboundWorkerV2 daemon."""

from typing import Any, Dict
from unittest.mock import MagicMock
import pytest

from scripts.outbound_worker_v2 import OutboundWorkerV2


def test_worker_instantiation_and_defaults() -> None:
    """Verifies OutboundWorkerV2 default configuration."""
    worker = OutboundWorkerV2(
        supabase_url="https://test.supabase.co",
        supabase_key="test-key",
        worker_id="test-worker-v2",
        poll_interval_seconds=1.0,
    )
    assert worker.worker_id == "test-worker-v2"
    assert worker.poll_interval == 1.0
    assert worker.running is True


def test_worker_claim_and_process_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that claiming an item invokes process_item and calls complete_item with lease_token."""
    worker = OutboundWorkerV2(
        supabase_url="https://test.supabase.co",
        supabase_key="test-key",
        worker_id="worker-test-1",
    )

    mock_client = MagicMock()
    mock_rpc = MagicMock()

    claim_response = MagicMock()
    claim_response.data = {
        "claimed": True,
        "item_id": "CVNI-20260802-120000-TEST",
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "lease_token": "CVNL-1234567890ABCDEF",
        "payload_json": {"content": {"title": "Test Title"}},
    }

    complete_response = MagicMock()
    complete_response.data = {"success": True, "item_id": "CVNI-20260802-120000-TEST", "status": "completed"}

    mock_rpc.execute.side_effect = [claim_response, complete_response]
    mock_client.rpc.return_value = mock_rpc

    monkeypatch.setattr(worker, "_client", mock_client)

    claimed = worker.claim_item()
    assert claimed is not None
    assert claimed["item_id"] == "CVNI-20260802-120000-TEST"
    assert claimed["lease_token"] == "CVNL-1234567890ABCDEF"

    success = worker.process_item(claimed)
    assert success is True

    # Verify RPC complete was called with lease_token
    mock_client.rpc.assert_called_with(
        "cvn_complete_outbound_item",
        {
            "p_item_id": "CVNI-20260802-120000-TEST",
            "p_worker_id": "worker-test-1",
            "p_lease_token": "CVNL-1234567890ABCDEF",
            "p_result_json": {
                "status": "delivered",
                "processed_at": pytest.any if hasattr(pytest, "any") else claimed.get("processed_at", None) or mock_client.rpc.call_args[0][1]["p_result_json"]["processed_at"],
                "target_agent": "openclaw",
                "worker_id": "worker-test-1",
            },
        },
    )


def test_worker_single_run_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that single-run mode executes once and exits when no items are claimed."""
    worker = OutboundWorkerV2(
        supabase_url="https://test.supabase.co",
        supabase_key="test-key",
        worker_id="worker-single-run",
    )

    mock_client = MagicMock()
    mock_rpc = MagicMock()
    no_item_response = MagicMock()
    no_item_response.data = None
    mock_rpc.execute.return_value = no_item_response
    mock_client.rpc.return_value = mock_rpc
    monkeypatch.setattr(worker, "_client", mock_client)

    processed = worker.run(single_run=True)
    assert processed == 0
