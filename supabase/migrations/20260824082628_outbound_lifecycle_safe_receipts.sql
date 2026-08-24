-- Preserve the most recent durable claim timestamp after lease ownership is
-- cleared by completion/failure RPCs. No new lifecycle table or column is
-- required; the canonical status RPC can continue returning claimed_at.
CREATE OR REPLACE FUNCTION public.cvn_preserve_outbound_claimed_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    IF OLD.claimed_at IS NOT NULL
       AND NEW.claimed_at IS NULL
       AND NEW.status IN (
           'completed',
           'failed_retryable',
           'failed_permanent',
           'dead_letter',
           'expired'
       ) THEN
        NEW.claimed_at := OLD.claimed_at;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_cvn_preserve_outbound_claimed_at
ON public.cvn_outbound_items;

CREATE TRIGGER trg_cvn_preserve_outbound_claimed_at
BEFORE UPDATE OF status, claimed_at ON public.cvn_outbound_items
FOR EACH ROW
EXECUTE FUNCTION public.cvn_preserve_outbound_claimed_at();

-- Migration 021 recreated this SECURITY DEFINER function after earlier grants,
-- which restored PostgreSQL's default PUBLIC execute privilege. Keep all
-- status reads behind the authenticated Edge Function/service role.
ALTER FUNCTION public.cvn_get_outbound_item_status(TEXT, TEXT)
SET search_path = '';

REVOKE ALL ON FUNCTION public.cvn_get_outbound_item_status(TEXT, TEXT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_get_outbound_item_status(TEXT, TEXT)
TO service_role;

REVOKE ALL ON FUNCTION public.cvn_preserve_outbound_claimed_at()
FROM PUBLIC, anon, authenticated;
