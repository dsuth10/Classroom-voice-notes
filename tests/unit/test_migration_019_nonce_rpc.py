# tests/unit/test_migration_019_nonce_rpc.py
from pathlib import Path

def test_migration_019_sql_structure_and_permissions() -> None:
    migration_file = Path("supabase/migrations/019_cvn_outbound_remediation_v3.sql")
    assert migration_file.exists(), "Migration 019 SQL file missing"
    content = migration_file.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.cvn_request_nonces" in content
    assert "PRIMARY KEY (credential_type, key_id, nonce)" in content
    assert "CREATE OR REPLACE FUNCTION public.cvn_register_request_nonce" in content
    assert "SECURITY DEFINER" in content
    assert "SET search_path = public" in content
    
    # Input parameter sanity checks
    assert "IF p_credential_type NOT IN ('worker', 'client') THEN" in content
    assert "IF p_key_id IS NULL OR length(p_key_id) > 64" in content
    assert "IF p_nonce IS NULL OR length(p_nonce) < 8 OR length(p_nonce) > 128 THEN" in content
    assert "IF p_ttl_seconds IS NULL OR p_ttl_seconds < 30 OR p_ttl_seconds > 900 THEN" in content
    
    # Permission hardening
    assert "REVOKE ALL ON FUNCTION public.cvn_register_request_nonce(text, text, text, bigint, integer) FROM PUBLIC, anon, authenticated;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_register_request_nonce(text, text, text, bigint, integer) TO service_role;" in content
