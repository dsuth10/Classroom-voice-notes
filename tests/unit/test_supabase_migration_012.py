"""Unit tests verifying SQL structure and RPC declarations in 012_cvn_outbound_v2_lifecycle.sql."""

from pathlib import Path
import pytest


def test_migration_012_file_exists() -> None:
    mig_file = Path("supabase/migrations/012_cvn_outbound_v2_lifecycle.sql")
    assert mig_file.exists()
    content = mig_file.read_text(encoding="utf-8")

    assert "cvn_claim_outbound_item" in content
    assert "cvn_complete_outbound_item" in content
    assert "cvn_fail_outbound_item" in content
    assert "cvn_get_outbound_item_status" in content
    assert "failed_retryable" in content
    assert "dead_letter" in content
    assert "visibility_deadline" in content
    assert "REVOKE ALL ON FUNCTION public.cvn_claim_outbound_item FROM PUBLIC, anon, authenticated;" in content
