from pathlib import Path


MIGRATION = Path(
    "supabase/migrations/20260811222905_harden_legacy_function_privileges.sql"
)

PRIVILEGED_SIGNATURES = (
    "public.cvn_claim_next_task(text, integer)",
    "public.cvn_claim_next_task(text, integer, text)",
    "public.cvn_complete_task(text, text, text)",
    "public.cvn_complete_task(text, text, text, text[])",
    "public.cvn_fail_task(text, text, text, text, text, integer)",
    "public.cvn_fail_task(text, text, text, text, text, integer, text[])",
    "public.cvn_fail_task(text, text, text, integer)",
    "public.cvn_reap_outbound_dead_letters(integer)",
    "public.cvn_reap_stale_claims(integer)",
)


def test_legacy_privileged_rpcs_are_private_to_service_role() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    for signature in PRIVILEGED_SIGNATURES:
        assert (
            f"REVOKE EXECUTE ON FUNCTION {signature}\n"
            "FROM PUBLIC, anon, authenticated;" in content
        )
        assert (
            f"GRANT EXECUTE ON FUNCTION {signature}\n" "TO service_role;" in content
        )

    submit_signature = """public.cvn_submit_task(
    text,
    text,
    text,
    text,
    jsonb,
    text,
    text,
    text,
    text[],
    jsonb,
    text,
    text,
    timestamp with time zone
)"""
    assert (
        f"REVOKE EXECUTE ON FUNCTION {submit_signature}\n"
        "FROM PUBLIC, anon, authenticated;" in content
    )
    assert (
        f"GRANT EXECUTE ON FUNCTION {submit_signature}\n" "TO service_role;"
        in content
    )


def test_trigger_search_path_and_future_function_defaults_are_hardened() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert (
        "ALTER FUNCTION public.cvn_task_events_block_modify()\n"
        "SET search_path = pg_catalog;" in content
    )
    assert (
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public\n"
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;" in content
    )
