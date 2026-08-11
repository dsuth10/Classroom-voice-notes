-- Harden legacy privileged functions that were explicitly granted to the
-- Data API roles by older Supabase default privileges. All normal application
-- calls reach these RPCs through Edge Functions using the service role.

BEGIN;

-- This trigger helper does not resolve database objects. Pinning its search
-- path to pg_catalog removes the mutable-path warning without changing its
-- append-only enforcement behaviour.
ALTER FUNCTION public.cvn_task_events_block_modify()
SET search_path = pg_catalog;

-- Legacy task lifecycle RPCs are internal broker operations. Revoke each exact
-- overloaded signature from public Data API roles and retain trusted server
-- access explicitly.
REVOKE EXECUTE ON FUNCTION public.cvn_claim_next_task(text, integer)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_claim_next_task(text, integer)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_claim_next_task(text, integer, text)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_claim_next_task(text, integer, text)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_complete_task(text, text, text)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_complete_task(text, text, text)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_complete_task(text, text, text, text[])
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_complete_task(text, text, text, text[])
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(text, text, text, text, text, integer)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(text, text, text, text, text, integer)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(text, text, text, text, text, integer, text[])
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(text, text, text, text, text, integer, text[])
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(text, text, text, integer)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(text, text, text, integer)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_reap_outbound_dead_letters(integer)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_reap_outbound_dead_letters(integer)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_reap_stale_claims(integer)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_reap_stale_claims(integer)
TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_submit_task(
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
)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_submit_task(
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
)
TO service_role;

-- New functions created by postgres must be explicitly exposed. Existing Edge
-- Function migrations already grant their intended RPCs to service_role.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

COMMIT;
