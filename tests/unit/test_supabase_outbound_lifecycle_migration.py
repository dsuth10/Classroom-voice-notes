from pathlib import Path


MIGRATION = Path(
    "supabase/migrations/20260824082628_outbound_lifecycle_safe_receipts.sql"
)


def test_lifecycle_migration_preserves_claimed_timestamp() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    assert "cvn_preserve_outbound_claimed_at" in content
    assert "NEW.claimed_at := OLD.claimed_at" in content
    assert "BEFORE UPDATE OF status, claimed_at" in content


def test_lifecycle_migration_restricts_status_rpc() -> None:
    content = MIGRATION.read_text(encoding="utf-8")
    signature = "public.cvn_get_outbound_item_status(TEXT, TEXT)"
    assert f"ALTER FUNCTION {signature}" in content
    assert "SET search_path = ''" in content
    assert f"REVOKE ALL ON FUNCTION {signature}" in content
    assert "FROM PUBLIC, anon, authenticated" in content
    assert f"GRANT EXECUTE ON FUNCTION {signature}" in content
    assert "TO service_role" in content
