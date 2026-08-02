"""Unit and SQL structural validation tests for Supabase authorization and immutability fixes."""

from pathlib import Path
import pytest


def test_migration_008_revokes_public_and_authenticated_grants() -> None:
    migration_file = Path("supabase/migrations/008_cvn_outbound_items.sql")
    content = migration_file.read_text(encoding="utf-8")

    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC;" in content
    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM anon;" in content
    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM authenticated;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO authenticated;" not in content


def test_migration_009_has_valid_dollar_quoting_and_idempotency() -> None:
    migration_file = Path("supabase/migrations/009_cvn_outbound_reaper.sql")
    content = migration_file.read_text(encoding="utf-8")

    assert "DO $block$" in content
    assert "$job$SELECT public.cvn_reap_outbound_dead_letters(30);$job$" in content
    assert "cron.unschedule('cvn-reap-outbound-items');" in content


def test_migration_010_forward_fix_structure() -> None:
    migration_file = Path("supabase/migrations/010_cvn_outbound_security_fix.sql")
    assert migration_file.exists()
    content = migration_file.read_text(encoding="utf-8")

    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item" in content
    assert "timestamp_skew" in content
    assert "invalid_schema_version" in content
    assert "SET search_path = public, pgmq, pg_temp" in content


def test_migration_017_immutability_and_worker_scoping() -> None:
    migration_file = Path("supabase/migrations/017_cvn_outbound_broker_immutability.sql")
    assert migration_file.exists(), f"Migration missing at {migration_file}"
    content = migration_file.read_text(encoding="utf-8")

    assert "trg_prevent_outbound_item_immutability" in content
    assert "immutable_column_violation" in content
    assert "missing_worker_id" in content
    assert "content_hash_mismatch" in content
    assert "payload_hash_mismatch" in content
    assert "unauthorized_device" in content
    assert "REVOKE ALL ON public.cvn_outbound_items FROM PUBLIC, anon, authenticated" in content


def test_all_migrations_exist_and_are_sequential() -> None:
    migrations_dir = Path("supabase/migrations")
    sql_files = sorted(migrations_dir.glob("*.sql"))
    names = [f.name for f in sql_files]

    expected = [
        "001_cvn_broker_mvp.sql",
        "002_pgmq_schema_grants.sql",
        "003_cvn_submit_task_security_definer.sql",
        "004_cvn_claim_complete_fail_status.sql",
        "005_cvn_reaper_jobs.sql",
        "006_cvn_phase_2c_broker_extensions.sql",
        "007_cvn_phase_2c1_auth_extensions.sql",
        "008_cvn_outbound_items.sql",
        "009_cvn_outbound_reaper.sql",
        "010_cvn_outbound_security_fix.sql",
        "016_cvn_trusted_device_entitlements_v2.sql",
        "017_cvn_outbound_broker_immutability.sql",
    ]

    for name in expected:
        assert name in names, f"Missing required migration file: {name}"
