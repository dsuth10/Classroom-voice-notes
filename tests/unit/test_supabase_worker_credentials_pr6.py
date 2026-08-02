"""Unit test verifying SQL Migration 014 and worker credential isolation / lease token enforcement contracts."""

from pathlib import Path
import pytest


def test_migration_014_file_structure() -> None:
    """Verifies that 014_cvn_worker_credentials.sql exists and enforces capability isolation & lease tokens."""
    migration_path = (
        Path(__file__).resolve().parent.parent.parent
        / "supabase"
        / "migrations"
        / "014_cvn_worker_credentials.sql"
    )
    assert migration_path.exists(), f"Migration missing at {migration_path}"
    content = migration_path.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS lease_token TEXT" in content
    assert "CREATE TABLE IF NOT EXISTS public.cvn_worker_credentials" in content
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "REVOKE ALL ON public.cvn_worker_credentials FROM PUBLIC, anon, authenticated" in content
    assert "GRANT ALL ON public.cvn_worker_credentials TO service_role" in content

    assert "cvn_verify_worker_credential" in content
    assert "REVOKE ALL ON FUNCTION public.cvn_verify_worker_credential FROM PUBLIC, anon, authenticated" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_verify_worker_credential TO service_role" in content

    assert "v_generated_lease" in content
    assert "invalid_lease_token" in content
