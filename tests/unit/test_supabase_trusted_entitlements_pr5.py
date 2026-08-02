"""Unit test verifying SQL Migration 013/016 and server trusted entitlement contracts."""

from pathlib import Path
import pytest


def test_migration_013_file_structure() -> None:
    """Verifies that 013_cvn_trusted_device_entitlements.sql exists and contains service-role restrictions."""
    migration_path = (
        Path(__file__).resolve().parent.parent.parent
        / "supabase"
        / "migrations"
        / "013_cvn_trusted_device_entitlements.sql"
    )
    assert migration_path.exists(), f"Migration missing at {migration_path}"
    content = migration_path.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.cvn_trusted_devices" in content
    assert "PRIMARY KEY (client_key_id, source_device_id)" in content
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "REVOKE ALL ON public.cvn_trusted_devices FROM PUBLIC, anon, authenticated" in content
    assert "GRANT ALL ON public.cvn_trusted_devices TO service_role" in content
    assert "cvn_evaluate_trusted_entitlement" in content
    assert "REVOKE ALL ON FUNCTION public.cvn_evaluate_trusted_entitlement FROM PUBLIC, anon, authenticated" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_evaluate_trusted_entitlement TO service_role" in content


def test_migration_016_file_structure() -> None:
    """Verifies that 016_cvn_trusted_device_entitlements_v2.sql exists and enforces environment PK and policy checks."""
    migration_path = (
        Path(__file__).resolve().parent.parent.parent
        / "supabase"
        / "migrations"
        / "016_cvn_trusted_device_entitlements_v2.sql"
    )
    assert migration_path.exists(), f"Migration missing at {migration_path}"
    content = migration_path.read_text(encoding="utf-8")

    assert "PRIMARY KEY (client_key_id, source_device_id, environment)" in content
    assert "check_maximum_risk" in content
    assert "check_allowed_item_kinds_nonempty" in content
    assert "check_allowed_target_agents_nonempty" in content
    assert "check_environment_valid" in content
    assert "policy_version_mismatch" in content


def test_edge_function_trusted_mode_unauthorized_handling() -> None:
    """Verifies edge function contains server-side entitlement evaluation for trusted_mode."""
    edge_fn_path = (
        Path(__file__).resolve().parent.parent.parent
        / "supabase"
        / "functions"
        / "cvn-submit-outbound-item"
        / "index.ts"
    )
    assert edge_fn_path.exists(), f"Edge function missing at {edge_fn_path}"
    content = edge_fn_path.read_text(encoding="utf-8")

    assert "cvn_evaluate_trusted_entitlement" in content
    assert "trusted_mode_unauthorized" in content
    assert "authenticateClient" in content
    assert "serverClientKeyId" in content
