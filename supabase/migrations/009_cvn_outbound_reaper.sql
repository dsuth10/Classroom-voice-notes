-- 009_cvn_outbound_reaper.sql
-- Phase 3: Outbound items reaper for dead letters and retention purging

BEGIN;

-- ============================================================================
-- 1. cvn_reap_outbound_dead_letters Function
-- ============================================================================
CREATE OR REPLACE FUNCTION public.cvn_reap_outbound_dead_letters(
    p_retention_days INT DEFAULT 30
) RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_purged INT;
BEGIN
    DELETE FROM public.cvn_outbound_items
    WHERE status IN ('completed', 'failed')
      AND created_at < (now() - (p_retention_days || ' days')::INTERVAL);
    
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$;

-- ============================================================================
-- 2. Schedule pg_cron Reaper Job
-- ============================================================================
DO $$ BEGIN
    PERFORM cron.schedule(
        'cvn-reap-outbound-items',
        '0 */12 * * *',
        $$ SELECT public.cvn_reap_outbound_dead_letters(30) $$
    );
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

COMMIT;
