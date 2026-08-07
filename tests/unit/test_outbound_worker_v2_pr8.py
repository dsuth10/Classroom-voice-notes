"""Unit tests for OutboundWorkerV2 daemon."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

from scripts.outbound_worker_v2 import OutboundWorkerV2


from pathlib import Path
from app.worker.journal import WorkerJournal


def test_worker_instantiation_and_defaults(tmp_path: Path) -> None:
    """Verifies OutboundWorkerV2 default configuration."""
    worker = OutboundWorkerV2(
        edge_base_url="https://test.supabase.co/functions/v1",
        worker_bearer_token="test-bearer",
        worker_hmac_secret="test-secret",
        worker_id="test-worker-v2",
        poll_interval_seconds=1.0,
        journal=WorkerJournal(db_path=tmp_path / "j1.db"),
    )
    assert worker.worker_id == "test-worker-v2"
    assert worker.worker_bearer_token == "test-bearer"
    assert worker.worker_hmac_secret == "test-secret"
    assert worker.poll_interval == 1.0
    assert worker.running is True


def test_worker_claim_and_process_item(tmp_path: Path) -> None:
    """Verifies that claiming an item invokes process_item and completes via Edge endpoint with HMAC headers."""
    worker = OutboundWorkerV2(
        edge_base_url="https://test.supabase.co/functions/v1",
        worker_bearer_token="test-bearer",
        worker_hmac_secret="test-secret",
        worker_id="worker-test-1",
        journal=WorkerJournal(db_path=tmp_path / "j2.db"),
    )

    from app.destinations.canonical_json import compute_canonical_content_hash
    content_data = {"title": "Test Title"}
    _, valid_hash = compute_canonical_content_hash("record_only", "openclaw", content_data)

    mock_resp_claim = MagicMock()
    mock_resp_claim.read.return_value = json.dumps({
        "claimed": True,
        "item_id": "CVNI-20260802-120000-TEST",
        "item_kind": "record_only",
        "target_agent": "openclaw",
        "lease_token": "test_mock_lease_token_12345",
        "payload_hash": valid_hash,
        "content_hash": valid_hash,
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "payload_json": {
            "schema_version": "cvn.outbound_item.v2",
            "item_kind": "record_only",
            "target_agent": "openclaw",
            "item_id": "CVNI-20260802-120000-TEST",
            "source_device_id": "dev-01",
            "created_at": "2026-08-03T10:00:00Z",
            "content_hash": valid_hash,
            "content": content_data,
            "privacy": {
                "automatic_classification": "non_sensitive",
                "risk_level": "low",
                "release_basis": "automatic_policy",
                "checks_passed": ["content_classification_pass"],
            },
        },
    }).encode("utf-8")
    mock_resp_claim.__enter__.return_value = mock_resp_claim

    mock_resp_complete = MagicMock()
    mock_resp_complete.read.return_value = json.dumps({
        "success": True,
        "item_id": "CVNI-20260802-120000-TEST",
        "status": "completed",
    }).encode("utf-8")
    mock_resp_complete.__enter__.return_value = mock_resp_complete

    with patch("urllib.request.urlopen", side_effect=[mock_resp_claim, mock_resp_complete]) as mock_urlopen:
        claimed = worker.claim_item()
        assert claimed is not None
        assert claimed["item_id"] == "CVNI-20260802-120000-TEST"
        assert claimed["lease_token"] == "test_mock_lease_token_12345"

        success = worker.process_item(claimed)
        assert success is True
        assert mock_urlopen.call_count == 2

        # Verify second request (complete_item) had X-CVN-Signature header
        complete_req = mock_urlopen.call_args_list[1][0][0]
        assert complete_req.headers.get("Authorization") == "Bearer test-bearer"
        assert complete_req.headers.get("X-cvn-key-id") == "worker-test-1"
        assert "X-cvn-signature" in complete_req.headers


def test_worker_single_run_exit(tmp_path: Path) -> None:
    """Verifies that single-run mode executes once and exits when no items are claimed."""
    worker = OutboundWorkerV2(
        edge_base_url="https://test.supabase.co/functions/v1",
        worker_bearer_token="test-bearer",
        worker_hmac_secret="test-secret",
        worker_id="worker-single-run",
        journal=WorkerJournal(db_path=tmp_path / "j3.db"),
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"claimed": False}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        processed = worker.run(single_run=True)
        assert processed == 0
