"""Unit test verifying SQL Migration 015 single table-backed lifecycle contract."""

from pathlib import Path
import pytest


def test_migration_015_file_structure() -> None:
    """Verifies that 015_cvn_single_table_lifecycle.sql exists and enforces single table-backed lifecycle."""
    migration_path = (
        Path(__file__).resolve().parent.parent.parent
        / "supabase"
        / "migrations"
        / "015_cvn_single_table_lifecycle.sql"
    )
    assert migration_path.exists(), f"Migration missing at {migration_path}"
    content = migration_path.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.cvn_submit_outbound_item" in content
    assert "INSERT INTO public.cvn_outbound_items" in content
    assert "pgmq.send" not in content
    assert "'status', 'submitted'" in content
    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC, anon, authenticated" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role" in content
