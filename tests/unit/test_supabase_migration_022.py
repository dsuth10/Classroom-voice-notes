from pathlib import Path


def test_request_nonce_table_is_private_but_service_role_remains_functional() -> None:
    migration_file = Path(
        "supabase/migrations/20260811221550_secure_cvn_request_nonces.sql"
    )
    assert migration_file.exists(), "Migration 022 SQL file missing"

    content = migration_file.read_text(encoding="utf-8")

    assert "ALTER TABLE public.cvn_request_nonces ENABLE ROW LEVEL SECURITY;" in content
    assert (
        "REVOKE ALL ON TABLE public.cvn_request_nonces\n"
        "FROM PUBLIC, anon, authenticated;" in content
    )
    assert "GRANT ALL ON TABLE public.cvn_request_nonces TO service_role;" in content
    assert "CREATE POLICY cvn_request_nonces_service_all" in content
    assert "TO service_role" in content
    assert "USING (true)" in content
    assert "WITH CHECK (true)" in content
