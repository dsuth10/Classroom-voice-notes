# tests/unit/test_migration_020_lease_idempotency.py
"""Unit tests verifying Migration 020 SQL structure, lease hashing, backoff logic, and idempotency RPC signatures."""
from pathlib import Path


def test_migration_020_sql_structure_and_permissions() -> None:
    migration_file = Path("supabase/migrations/020_cvn_lease_hash_and_idempotency.sql")
    assert migration_file.exists(), "Migration 020 SQL file missing"
    content = migration_file.read_text(encoding="utf-8")

    # Column additions
    assert "ADD COLUMN IF NOT EXISTS lease_token_hash TEXT" in content
    assert "ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ" in content
    assert "ADD COLUMN IF NOT EXISTS last_error_code TEXT" in content
    assert "ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ" in content
    assert "ADD COLUMN IF NOT EXISTS result_reference TEXT" in content
    assert "check_outbound_lease_token_hash_hex" in content

    # Lease migration of legacy active claims
    assert "SET status = 'failed_retryable'" in content
    assert "lease_token_hash IS NULL" in content

    # Performance Index
    assert "CREATE INDEX IF NOT EXISTS idx_cvn_outbound_items_claim_eligible" in content
    assert "WHERE status IN ('submitted', 'received', 'failed_retryable')" in content

    # cvn_submit_outbound_item Idempotency exact match vs conflict
    assert "idempotency_conflict:" in content
    assert "idempotent_replay" in content

    # cvn_claim_outbound_item hashed lease generation
    assert "v_lease_token :=" in content
    assert "gen_random_bytes(32)" in content
    assert "sha256(convert_to(v_lease_token, 'UTF8'))" in content
    assert "next_attempt_at IS NULL OR next_attempt_at <= now()" in content
    assert "FOR UPDATE SKIP LOCKED" in content

    # cvn_complete_outbound_item hashed lease validation & lease token cleanup
    assert "v_given_lease_hash :=" in content
    assert "lease_token_hash IS DISTINCT FROM v_given_lease_hash" in content
    assert "lease_token_hash = NULL" in content

    # cvn_fail_outbound_item server-controlled max attempts & ownership cleanup
    assert "v_max_attempts CONSTANT INT := 3;" in content
    assert "claimed_by = NULL" in content
    assert "claimed_by_worker_id = NULL" in content
    assert "claimed_at = NULL" in content
    assert "v_backoff_seconds :=" in content
    assert "LEAST(3600" in content
    assert "v_next_status := 'dead_letter'" in content

    # Permissions
    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC, anon, authenticated;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item(text, integer, text[], text[]) TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item(text, text, text, text, text, jsonb, text) TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item(text, text, text, text, boolean, text) TO service_role;" in content
