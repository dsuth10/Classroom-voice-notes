-- 005_cvn_reaper_jobs.sql
-- Enables pg_cron extension (if not already enabled) and schedules the background stale claims reaper.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_cron SCHEMA extensions;

-- Schedule the reaper job to run every 5 minutes
-- Wraps in a select to verify if scheduled, using standard cron schema schedule function
SELECT cron.schedule(
  'cvn-reap-stale-claims',
  '*/5 * * * *',
  $$ SELECT public.cvn_reap_stale_claims(5) $$
);

COMMIT;
