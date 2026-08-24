"""Unit tests verifying structural integrity of PR 8 Worker Edge Functions."""

from pathlib import Path
import pytest


def test_pr8_edge_functions_exist() -> None:
    auth_file = Path("supabase/functions/_shared/broker_auth.ts")
    assert auth_file.exists(), "broker_auth.ts missing"
    auth_content = auth_file.read_text(encoding="utf-8")
    assert "timingSafeEqual" in auth_content
    assert "authenticateWorker" in auth_content

    funcs = ["cvn-claim-outbound-item", "cvn-complete-outbound-item", "cvn-fail-outbound-item"]
    for func in funcs:
        edge_file = Path(f"supabase/functions/{func}/index.ts")
        assert edge_file.exists(), f"{func} index.ts missing"
        content = edge_file.read_text(encoding="utf-8")
        assert "authenticateWorker" in content

    status_content = Path(
        "supabase/functions/cvn-outbound-status/index.ts"
    ).read_text(encoding="utf-8")
    assert "authenticateClient" in status_content
    assert "p_source_device_id: authorisedSourceDeviceId" in status_content
    assert "Lifecycle-only allowlist" in status_content
    assert "result_reference: safeResultReference" in status_content
    assert "blocked_reason:" in status_content
    assert "item_kind: row.item_kind" not in status_content
    assert "safeResultReference" in status_content
    assert "authenticateWorker" not in status_content
