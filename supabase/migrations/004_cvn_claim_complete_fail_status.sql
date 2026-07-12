-- 004_cvn_claim_complete_fail_status.sql
-- Milestone 2: Alters cvn_tasks, adds nonce protection table, implements stored procedures for task lifecycle.

BEGIN;

-- ============================================================================
-- 1. Alter cvn_tasks to store pgmq message ID
-- ============================================================================
ALTER TABLE public.cvn_tasks ADD COLUMN IF NOT EXISTS queue_msg_id BIGINT;

-- ============================================================================
-- 2. Create nonce tracking table for replay protection
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.cvn_processed_nonces (
  nonce TEXT PRIMARY KEY,
  worker_id TEXT,
  endpoint TEXT NOT NULL,
  signed_at TIMESTAMPTZ NOT NULL,
  request_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cvn_processed_nonces_signed_at
  ON public.cvn_processed_nonces(signed_at);

-- RLS for nonces table: service_role can read/write
ALTER TABLE public.cvn_processed_nonces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cvn_processed_nonces_service_all ON public.cvn_processed_nonces;
CREATE POLICY cvn_processed_nonces_service_all ON public.cvn_processed_nonces
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================================
-- 3. Stale claim reaper function
-- ============================================================================
CREATE OR REPLACE FUNCTION public.cvn_reap_stale_claims(
  p_max_retries INT DEFAULT 5
)
RETURNS TABLE (
  reaped_count INT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq, pg_temp
AS $$
DECLARE
  v_task RECORD;
  v_reaped_count INT := 0;
BEGIN
  -- Find stale claimed tasks where expires_at has passed
  FOR v_task IN
    SELECT task_id, retry_count, claimed_by, queue_msg_id
    FROM public.cvn_tasks
    WHERE status IN ('claimed', 'running') AND expires_at < now()
    FOR UPDATE
  LOOP
    -- Increment retry count
    v_task.retry_count := v_task.retry_count + 1;

    IF v_task.retry_count < p_max_retries THEN
      -- Requeue: status back to pending, clear worker info, set VT to 0
      UPDATE public.cvn_tasks
      SET
        status = 'pending',
        retry_count = v_task.retry_count,
        claimed_by = NULL,
        claimed_at = NULL,
        expires_at = NULL,
        error_message = 'Claim expired'
      WHERE public.cvn_tasks.task_id = v_task.task_id;

      INSERT INTO public.cvn_task_events (
        task_id, event_type, actor, metadata
      ) VALUES (
        v_task.task_id,
        'requeued',
        'system_reaper',
        jsonb_build_object(
          'reason', 'claim_timeout',
          'retry_count', v_task.retry_count,
          'previous_worker', v_task.claimed_by,
          'queue_msg_id', v_task.queue_msg_id
        )
      );

      -- Reset message visibility in PGMQ to make it visible immediately
      IF v_task.queue_msg_id IS NOT NULL THEN
        PERFORM pgmq.set_vt('cvn_tasks_queue', v_task.queue_msg_id, 0);
      END IF;
    ELSE
      -- Move to dead letter
      UPDATE public.cvn_tasks
      SET
        status = 'dead_letter',
        retry_count = v_task.retry_count,
        claimed_by = NULL,
        claimed_at = NULL,
        expires_at = NULL,
        error_message = 'Claim expired (max retries reached)'
      WHERE public.cvn_tasks.task_id = v_task.task_id;

      INSERT INTO public.cvn_task_events (
        task_id, event_type, actor, metadata
      ) VALUES (
        v_task.task_id,
        'dead_letter',
        'system_reaper',
        jsonb_build_object(
          'reason', 'claim_timeout_max_retries',
          'retry_count', v_task.retry_count,
          'previous_worker', v_task.claimed_by,
          'queue_msg_id', v_task.queue_msg_id
        )
      );

      -- Delete from active queue
      IF v_task.queue_msg_id IS NOT NULL THEN
        PERFORM pgmq.delete('cvn_tasks_queue', v_task.queue_msg_id);
      END IF;
    END IF;

    v_reaped_count := v_reaped_count + 1;
  END LOOP;

  reaped_count := v_reaped_count;
  RETURN NEXT;
END;
$$;

-- ============================================================================
-- 4. Claim next task function
-- ============================================================================
CREATE OR REPLACE FUNCTION public.cvn_claim_next_task(
  p_worker_id TEXT,
  p_vt_seconds INT
)
RETURNS TABLE (
  task_id TEXT,
  target_agent TEXT,
  status cvn_task_status,
  payload_json JSONB,
  claimed BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq, pg_temp
AS $$
DECLARE
  v_msg_id BIGINT;
  v_message JSONB;
  v_task_id TEXT;
  v_status cvn_task_status;
  v_target_agent TEXT;
  v_payload_json JSONB;
BEGIN
  -- 1. Perform a cleanup pass on stale claims and old nonces
  PERFORM public.cvn_reap_stale_claims(5);
  DELETE FROM public.cvn_processed_nonces WHERE signed_at < now() - INTERVAL '5 minutes';

  -- 2. Read one message from PGMQ
  SELECT msg_id, message
  FROM pgmq.read('cvn_tasks_queue', p_vt_seconds, 1)
  LIMIT 1
  INTO v_msg_id, v_message;

  IF v_msg_id IS NULL THEN
    RETURN QUERY SELECT
      NULL::TEXT,
      NULL::TEXT,
      NULL::cvn_task_status,
      NULL::JSONB,
      FALSE;
    RETURN;
  END IF;

  v_task_id := v_message->>'task_id';

  -- 3. Lock task row
  SELECT public.cvn_tasks.status, public.cvn_tasks.target_agent, public.cvn_tasks.payload_json
  FROM public.cvn_tasks
  WHERE public.cvn_tasks.task_id = v_task_id
  FOR UPDATE
  INTO v_status, v_target_agent, v_payload_json;

  IF v_status IS NULL THEN
    -- Task row missing, clean queue message
    PERFORM pgmq.delete('cvn_tasks_queue', v_msg_id);
    RETURN QUERY SELECT
      NULL::TEXT,
      NULL::TEXT,
      NULL::cvn_task_status,
      NULL::JSONB,
      FALSE;
    RETURN;
  END IF;

  -- If completed, cancelled, or dead-letter, remove from queue and claim nothing
  IF v_status IN ('completed', 'cancelled', 'dead_letter') THEN
    PERFORM pgmq.delete('cvn_tasks_queue', v_msg_id);
    RETURN QUERY SELECT
      NULL::TEXT,
      NULL::TEXT,
      NULL::cvn_task_status,
      NULL::JSONB,
      FALSE;
    RETURN;
  END IF;

  -- 4. Update task details
  UPDATE public.cvn_tasks
  SET
    status = 'claimed',
    claimed_by = p_worker_id,
    claimed_at = now(),
    expires_at = now() + (p_vt_seconds || ' seconds')::interval,
    queue_msg_id = v_msg_id
  WHERE public.cvn_tasks.task_id = v_task_id;

  -- 5. Record claimed event
  INSERT INTO public.cvn_task_events (
    task_id, event_type, actor, metadata
  ) VALUES (
    v_task_id,
    'claimed',
    p_worker_id,
    jsonb_build_object(
      'queue_msg_id', v_msg_id,
      'vt_seconds', p_vt_seconds,
      'expires_at', now() + (p_vt_seconds || ' seconds')::interval
    )
  );

  RETURN QUERY SELECT
    v_task_id,
    v_target_agent,
    'claimed'::cvn_task_status,
    v_payload_json,
    TRUE;
END;
$$;

-- ============================================================================
-- 5. Complete task function
-- ============================================================================
CREATE OR REPLACE FUNCTION public.cvn_complete_task(
  p_task_id TEXT,
  p_worker_id TEXT,
  p_result_summary TEXT
)
RETURNS TABLE (
  success BOOLEAN,
  message TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq, pg_temp
AS $$
DECLARE
  v_status cvn_task_status;
  v_claimed_by TEXT;
  v_msg_id BIGINT;
BEGIN
  -- Lock task row
  SELECT status, claimed_by, queue_msg_id
  FROM public.cvn_tasks
  WHERE public.cvn_tasks.task_id = p_task_id
  FOR UPDATE
  INTO v_status, v_claimed_by, v_msg_id;

  IF v_status IS NULL THEN
    RETURN QUERY SELECT FALSE, 'task_not_found';
    RETURN;
  END IF;

  -- Idempotency
  IF v_status = 'completed' THEN
    RETURN QUERY SELECT TRUE, 'already_completed';
    RETURN;
  END IF;

  -- Check status is claimable/running
  IF v_status NOT IN ('claimed', 'running') THEN
    RETURN QUERY SELECT FALSE, 'invalid_status_for_completion';
    RETURN;
  END IF;

  -- Check claiming worker matches to prevent collision
  IF v_claimed_by IS DISTINCT FROM p_worker_id THEN
    RETURN QUERY SELECT FALSE, 'task_claimed_by_another_worker';
    RETURN;
  END IF;

  -- Update task details
  UPDATE public.cvn_tasks
  SET
    status = 'completed',
    result_summary = p_result_summary,
    completed_at = now(),
    queue_msg_id = NULL
  WHERE public.cvn_tasks.task_id = p_task_id;

  -- Record event
  INSERT INTO public.cvn_task_events (
    task_id, event_type, actor, metadata
  ) VALUES (
    p_task_id,
    'completed',
    p_worker_id,
    jsonb_build_object('result_summary', p_result_summary)
  );

  -- Archive from pgmq queue (retains it in pgmq archive table)
  IF v_msg_id IS NOT NULL THEN
    PERFORM pgmq.archive('cvn_tasks_queue', v_msg_id);
  END IF;

  RETURN QUERY SELECT TRUE, 'completed';
END;
$$;

-- ============================================================================
-- 6. Fail task function
-- ============================================================================
CREATE OR REPLACE FUNCTION public.cvn_fail_task(
  p_task_id TEXT,
  p_worker_id TEXT,
  p_error_message TEXT,
  p_max_retries INT DEFAULT 5
)
RETURNS TABLE (
  success BOOLEAN,
  status cvn_task_status,
  retry_count INT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq, pg_temp
AS $$
DECLARE
  v_status cvn_task_status;
  v_claimed_by TEXT;
  v_retry_count INT;
  v_msg_id BIGINT;
  v_new_status cvn_task_status;
BEGIN
  -- Lock task row
  SELECT public.cvn_tasks.status, public.cvn_tasks.claimed_by, public.cvn_tasks.retry_count, public.cvn_tasks.queue_msg_id
  FROM public.cvn_tasks
  WHERE public.cvn_tasks.task_id = p_task_id
  FOR UPDATE
  INTO v_status, v_claimed_by, v_retry_count, v_msg_id;

  IF v_status IS NULL THEN
    RETURN QUERY SELECT FALSE, NULL::cvn_task_status, NULL::INT;
    RETURN;
  END IF;

  -- Idempotency for terminal states
  IF v_status IN ('completed', 'cancelled', 'dead_letter') THEN
    RETURN QUERY SELECT TRUE, v_status, v_retry_count;
    RETURN;
  END IF;

  -- Prevent worker collision
  IF v_claimed_by IS DISTINCT FROM p_worker_id THEN
    RETURN QUERY SELECT FALSE, v_status, v_retry_count;
    RETURN;
  END IF;

  v_retry_count := v_retry_count + 1;

  IF v_retry_count < p_max_retries THEN
    -- Requeue: status back to pending, clear worker details, set message visible
    v_new_status := 'pending';

    UPDATE public.cvn_tasks
    SET
      status = v_new_status,
      retry_count = v_retry_count,
      failed_at = now(),
      error_message = p_error_message,
      claimed_by = NULL,
      claimed_at = NULL,
      expires_at = NULL,
      queue_msg_id = NULL
    WHERE public.cvn_tasks.task_id = p_task_id;

    INSERT INTO public.cvn_task_events (
      task_id, event_type, actor, metadata
    ) VALUES (
      p_task_id,
      'failed',
      p_worker_id,
      jsonb_build_object(
        'error_message', p_error_message,
        'retry_count', v_retry_count,
        'action', 'requeued'
      )
    );

    IF v_msg_id IS NOT NULL THEN
      PERFORM pgmq.set_vt('cvn_tasks_queue', v_msg_id, 0);
    END IF;

  ELSE
    -- Reached limit: mark dead_letter, delete queue message
    v_new_status := 'dead_letter';

    UPDATE public.cvn_tasks
    SET
      status = v_new_status,
      retry_count = v_retry_count,
      failed_at = now(),
      error_message = p_error_message,
      claimed_by = NULL,
      claimed_at = NULL,
      expires_at = NULL,
      queue_msg_id = NULL
    WHERE public.cvn_tasks.task_id = p_task_id;

    INSERT INTO public.cvn_task_events (
      task_id, event_type, actor, metadata
    ) VALUES (
      p_task_id,
      'dead_letter',
      p_worker_id,
      jsonb_build_object(
        'error_message', p_error_message,
        'retry_count', v_retry_count,
        'action', 'dead_letter'
      )
    );

    IF v_msg_id IS NOT NULL THEN
      PERFORM pgmq.delete('cvn_tasks_queue', v_msg_id);
    END IF;
  END IF;

  RETURN QUERY SELECT TRUE, v_new_status, v_retry_count;
END;
$$;

-- ============================================================================
-- 7. Permissions and Grants
-- ============================================================================
REVOKE EXECUTE ON FUNCTION public.cvn_claim_next_task(TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_claim_next_task(TEXT, INT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_complete_task(TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_complete_task(TEXT, TEXT, TEXT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, INT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_reap_stale_claims(INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_reap_stale_claims(INT) TO service_role;

COMMIT;
