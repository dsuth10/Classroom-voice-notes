-- 003_cvn_submit_task_security_definer.sql
-- Alters cvn_submit_task to run as SECURITY DEFINER with a restricted search path
BEGIN;

ALTER FUNCTION public.cvn_submit_task(
  p_task_id TEXT,
  p_source_device_id TEXT,
  p_target_agent TEXT,
  p_priority TEXT,
  p_payload_json JSONB,
  p_payload_hash TEXT,
  p_privacy_classification TEXT,
  p_policy_gate_version TEXT,
  p_checks_passed TEXT[],
  p_redactions_applied JSONB,
  p_idempotency_key TEXT,
  p_nonce TEXT,
  p_signed_at TIMESTAMPTZ
) SECURITY DEFINER SET search_path = public, pgmq, pg_temp;

-- Verify execute permissions are limited to service_role and postgres
REVOKE EXECUTE ON FUNCTION public.cvn_submit_task(
  TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT,
  TEXT[], JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.cvn_submit_task(
  TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT,
  TEXT[], JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO service_role;

COMMIT;
