"""Unit tests verifying structural integrity of PR 8 Worker Edge Functions."""

from pathlib import Path
import pytest


def test_pr8_edge_functions_exist() -> None:
    auth_file = Path("supabase/functions/_shared/broker_auth.ts")
    assert auth_file.exists(), "broker_auth.ts missing"
    auth_content = auth_file.read_text(encoding="utf-8")
    assert "timingSafeEqual" in auth_content
    assert "authenticateWorker" in auth_content

    funcs = ["cvn-claim-outbound-item", "cvn-complete-outbound-item", "cvn-fail-outbound-item", "cvn-outbound-status"]
    for func in funcs:
        edge_file = Path(f"supabase/functions/{func}/index.ts")
        assert edge_file.exists(), f"{func} index.ts missing"
        content = edge_file.read_text(encoding="utf-8")
        assert "authenticateWorker" in content
