"""Unit tests verifying structural integrity of PR 8 Worker Edge Functions."""

from pathlib import Path
import pytest


def test_pr8_edge_functions_exist() -> None:
    funcs = ["cvn-claim-outbound-item", "cvn-complete-outbound-item", "cvn-fail-outbound-item", "cvn-outbound-status"]
    for func in funcs:
      edge_file = Path(f"supabase/functions/{func}/index.ts")
      assert edge_file.exists(), f"{func} index.ts missing"
      content = edge_file.read_text(encoding="utf-8")
      assert "timingSafeEqual" in content
      assert "CVN_WORKER_BEARER_TOKEN" in content or "CVN_BEARER_TOKEN" in content
