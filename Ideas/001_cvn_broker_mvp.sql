-- 001_cvn_broker_mvp.sql  (revised)
-- CVN broker MVP: enums, tables, queue, stored procedure
-- Apply with: supabase db push   (after `supabase link --project-ref <ref>`)
-- Or directly: psql "$DATABASE_URL" -f 001_cvn_broker_mvp.sql
--
-- Non-destructive: only adds new objects. Does not touch agent_logs / todos /
-- content_files / jcodemunch_savings_logs.
--
-- Revisions in this pass:
--   1. Replaced pgmq.queue check with pgmq.list_queues()
--   2. DROP POLICY IF EXISTS before each CREATE POLICY (idempotent re-runs)
--   3. Tightened privacy_classification: table CHECK = 'non_sensitive',
--      default = 'non_sensitive', cvn_submit_task raises ERRCODE 23514 otherwise
--   4. UNIQUE (source_device_id, nonce) constraint
--   5. cvn_task_events.task_id FK changed from ON DELETE CASCADE to ON DELETE RESTRICT
--      (events outlive tasks; deletion blocked while events exist)

BEGIN;

-- ============================================================================
-- 1. Extensions
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pgmq;
-- pg_cron intentionally NOT enabled in MVP (no reaper yet)

-- ============================================================================
-- 2. Enums
-- ============================================================================
DO $$ BEGIN
  CREATE TYPE cvn_task_status AS ENUM (
    'pending',     -- just created, waiting in queue
    'claimed',     -- agent picked it up
    'running',     -- agent is processing
    'completed',   -- success
    'failed',      -- failure (retry counter incremented)
    'dead_letter', -- exceeded retry limit
    'cancelled'    -- manually cancelled
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE cvn_priority AS ENUM (
    'low',
    'normal',
    'high',
    'urgent'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- 3. cvn_tasks — durable task record
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.cvn_tasks (
  task_id TEXT PRIMARY KEY
    CHECK (task_id ~ '^CVN-[0-9]{8}-[0-9]{6}-[A-Z0-9]{4}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_device_id TEXT NOT NULL,
  target_agent TEXT NOT NULL
    CHECK (target_agent IN ('hermes', 'openclaw', 'auto')),
  status cvn_task_status NOT NULL DEFAULT 'pending',
  priority cvn_priority NOT NULL DEFAULT 'normal',
  payload_json JSONB NOT NULL,
  payload_hash TEXT NOT NULL,
  privacy_classification TEXT NOT NULL DEFAULT 'non_sensitive'
    CONSTRAINT cvn_tasks_privacy_classification_non_sensitive
    CHECK (privacy_classification = 'non_sensitive'),
  policy_gate_version TEXT NOT NULL,
  checks_passed TEXT[] NOT NULL,
  redactions_applied JSONB NOT NULL DEFAULT '[]'::jsonb,
  idempotency_key TEXT NOT NULL UNIQUE,
  nonce TEXT NOT NULL,
  signed_at TIMESTAMPTZ NOT NULL,
  claimed_by TEXT,
  claimed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  failed_at TIMESTAMPTZ,
  result_summary TEXT,
  error_message TEXT,
  retry_count INT NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ,
  CONSTRAINT cvn_tasks_source_device_id_nonce UNIQUE (source_device_id, nonce)
);

CREATE INDEX IF NOT EXISTS idx_cvn_tasks_status ON public.cvn_tasks(status);
CREATE INDEX IF NOT EXISTS idx_cvn_tasks_target_agent ON public.cvn_tasks(target_agent);
CREATE INDEX IF NOT EXISTS idx_cvn_tasks_created_at ON public.cvn_tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cvn_tasks_claimed_by ON public.cvn_tasks(claimed_by);

-- ============================================================================
-- 4. cvn_task_events — append-only audit log
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.cvn_task_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id TEXT NOT NULL REFERENCES public.cvn_tasks(task_id) ON DELETE RESTRICT,
  event_type TEXT NOT NULL CHECK (event_type IN (
    'submitted', 'claimed', 'route_decision', 'completed',
    'failed', 'requeued', 'dead_letter', 'cancelled'
  )),
  event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor TEXT NOT NULL,
  payload_hash TEXT,
  signature TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_cvn_task_events_task_id
  ON public.cvn_task_events(task_id, event_at);
CREATE INDEX IF NOT EXISTS idx_cvn_task_events_event_type
  ON public.cvn_task_events(event_type);

-- Append-only enforcement: trigger blocks UPDATE/DELETE for ALL roles
-- (including service_role). RLS provides a second layer.
CREATE OR REPLACE FUNCTION public.cvn_task_events_block_modify()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'cvn_task_events is append-only; UPDATE/DELETE not allowed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cvn_task_events_no_update ON public.cvn_task_events;
CREATE TRIGGER cvn_task_events_no_update
BEFORE UPDATE ON public.cvn_task_events
FOR EACH ROW EXECUTE FUNCTION public.cvn_task_events_block_modify();

DROP TRIGGER IF EXISTS cvn_task_events_no_delete ON public.cvn_task_events;
CREATE TRIGGER cvn_task_events_no_delete
BEFORE DELETE ON public.cvn_task_events
FOR EACH ROW EXECUTE FUNCTION public.cvn_task_events_block_modify();

-- RLS: insert + select for service_role, no update/delete policies
ALTER TABLE public.cvn_task_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cvn_task_events_service_insert ON public.cvn_task_events;
CREATE POLICY cvn_task_events_service_insert ON public.cvn_task_events
  FOR INSERT TO service_role WITH CHECK (true);

DROP POLICY IF EXISTS cvn_task_events_service_select ON public.cvn_task_events;
CREATE POLICY cvn_task_events_service_select ON public.cvn_task_events
  FOR SELECT TO service_role USING (true);

-- ============================================================================
-- 5. RLS for cvn_tasks
-- ============================================================================
ALTER TABLE public.cvn_tasks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cvn_tasks_service_all ON public.cvn_tasks;
CREATE POLICY cvn_tasks_service_all ON public.cvn_tasks
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ============================================================================
-- 6. pgmq queue (task_id only, no payload)
-- ============================================================================
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pgmq.list_queues() WHERE queue_name = 'cvn_tasks_queue'
  ) THEN
    PERFORM pgmq.create('cvn_tasks_queue');
  END IF;
END $$;

-- ============================================================================
-- 7. Atomic submit function (task + event + queue in one transaction)
-- ============================================================================
CREATE OR REPLACE FUNCTION public.cvn_submit_task(
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
)
RETURNS TABLE (task_id TEXT, status_url TEXT, msg_id BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
  v_msg_id BIGINT;
BEGIN
  -- Belt-and-braces: reject anything other than 'non_sensitive'.
  -- The Edge Function validates this first, but the DB is the last line
  -- of defense if the RPC is called directly.
  IF p_privacy_classification IS DISTINCT FROM 'non_sensitive' THEN
    RAISE EXCEPTION
      'privacy_classification must be non_sensitive, got: %', p_privacy_classification
      USING ERRCODE = '23514';
  END IF;

  -- Reject duplicate idempotency_key (race-safe via UNIQUE constraint)
  IF EXISTS (
    SELECT 1 FROM public.cvn_tasks WHERE idempotency_key = p_idempotency_key
  ) THEN
    RAISE EXCEPTION 'duplicate_idempotency_key'
      USING ERRCODE = '23505';
  END IF;

  -- Reject duplicate (source_device_id, nonce)
  IF EXISTS (
    SELECT 1 FROM public.cvn_tasks
    WHERE source_device_id = p_source_device_id AND nonce = p_nonce
  ) THEN
    RAISE EXCEPTION 'duplicate_device_nonce'
      USING ERRCODE = '23505';
  END IF;

  -- Insert into cvn_tasks
  INSERT INTO public.cvn_tasks (
    task_id, source_device_id, target_agent, status, priority,
    payload_json, payload_hash, privacy_classification, policy_gate_version,
    checks_passed, redactions_applied, idempotency_key, nonce, signed_at
  ) VALUES (
    p_task_id, p_source_device_id, p_target_agent, 'pending', p_priority,
    p_payload_json, p_payload_hash, p_privacy_classification, p_policy_gate_version,
    p_checks_passed, p_redactions_applied, p_idempotency_key, p_nonce, p_signed_at
  );

  -- Insert into cvn_task_events
  INSERT INTO public.cvn_task_events (
    task_id, event_type, actor, payload_hash, metadata
  ) VALUES (
    p_task_id, 'submitted', p_source_device_id, p_payload_hash,
    jsonb_build_object(
      'checks_passed', to_jsonb(p_checks_passed),
      'redactions_applied', p_redactions_applied
    )
  );

  -- Enqueue to pgmq (message body = task_id + enqueued_at, no payload)
  SELECT pgmq.send(
    'cvn_tasks_queue',
    jsonb_build_object(
      'task_id', p_task_id,
      'enqueued_at', extract(epoch from now())
    )
  ) INTO v_msg_id;

  RETURN QUERY SELECT
    p_task_id,
    '/functions/v1/cvn-status/' || p_task_id,
    v_msg_id;
END;
$$;

-- Grant execute to service_role (Edge Function uses service_role key)
GRANT EXECUTE ON FUNCTION public.cvn_submit_task(
  TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT,
  TEXT[], JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO service_role;

COMMIT;
