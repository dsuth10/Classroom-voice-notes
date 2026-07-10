-- 006_cvn_phase_2c_broker_extensions.sql
-- Phase 2C.0: Support manual_review, error_code, target-specific claiming, and failure dispositions.

-- 1. Alter Type cvn_task_status (must run outside the migration transaction block in PostgreSQL < 16)
COMMIT;

ALTER TYPE public.cvn_task_status ADD VALUE IF NOT EXISTS 'manual_review';

BEGIN;

-- 2. Alter cvn_tasks to store specific error codes
ALTER TABLE public.cvn_tasks ADD COLUMN IF NOT EXISTS error_code TEXT;

-- 3. Update task event type checks to allow 'manual_review' as a valid event type
ALTER TABLE public.cvn_task_events DROP CONSTRAINT IF EXISTS cvn_task_events_event_type_check;
ALTER TABLE public.cvn_task_events ADD CONSTRAINT cvn_task_events_event_type_check CHECK (event_type IN (
  'submitted', 'claimed', 'route_decision', 'completed',
  'failed', 'requeued', 'dead_letter', 'cancelled', 'manual_review'
));

-- 4. Initialise target-specific PGMQ queues
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pgmq.list_queues() WHERE queue_name = 'cvn_tasks_queue_openclaw') THEN
    PERFORM pgmq.create('cvn_tasks_queue_openclaw');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pgmq.list_queues() WHERE queue_name = 'cvn_tasks_queue_hermes') THEN
    PERFORM pgmq.create('cvn_tasks_queue_hermes');
  END IF;
END $$;

-- 5. Stale claim reaper function (modified to support multiple target queues)
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
  v_queue_name TEXT;
BEGIN
  -- Find stale claimed tasks where expires_at has passed
  FOR v_task IN 
    SELECT task_id, retry_count, claimed_by, queue_msg_id, target_agent
    FROM public.cvn_tasks
    WHERE status IN ('claimed', 'running') AND expires_at < now()
    FOR UPDATE
  LOOP
    -- Increment retry count
    v_task.retry_count := v_task.retry_count + 1;

    -- Resolve queue name dynamically
    IF v_task.target_agent = 'openclaw' THEN
      v_queue_name := 'cvn_tasks_queue_openclaw';
    ELSE
      v_queue_name := 'cvn_tasks_queue_hermes';
    END IF;

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
          'queue_msg_id', v_task.queue_msg_id,
          'queue_name', v_queue_name
        )
      );

      -- Reset message visibility in target PGMQ queue to make it visible immediately
      IF v_task.queue_msg_id IS NOT NULL THEN
        PERFORM pgmq.set_vt(v_queue_name, v_task.queue_msg_id, 0);
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
          'queue_msg_id', v_task.queue_msg_id,
          'queue_name', v_queue_name
        )
      );

      -- Delete from target queue
      IF v_task.queue_msg_id IS NOT NULL THEN
        PERFORM pgmq.delete(v_queue_name, v_task.queue_msg_id);
      END IF;
    END IF;

    v_reaped_count := v_reaped_count + 1;
  END LOOP;

  reaped_count := v_reaped_count;
  RETURN NEXT;
END;
$$;

-- 6. Submit task function (modified to route to target-specific queues)
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
SECURITY DEFINER
SET search_path = public, pgmq, pg_temp
AS $$
DECLARE
  v_msg_id BIGINT;
  v_queue_name TEXT;
BEGIN
  -- Belt-and-braces: reject anything other than 'non_sensitive'.
  IF p_privacy_classification IS DISTINCT FROM 'non_sensitive' THEN
    RAISE EXCEPTION
      'privacy_classification must be non_sensitive, got: %', p_privacy_classification
      USING ERRCODE = '23514';
  END IF;

  -- Reject duplicate idempotency_key
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
    p_task_id, p_source_device_id, p_target_agent, 'pending', p_priority::cvn_priority,
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

  -- Determine queue based on target agent
  IF p_target_agent = 'openclaw' THEN
    v_queue_name := 'cvn_tasks_queue_openclaw';
  ELSE
    v_queue_name := 'cvn_tasks_queue_hermes';
  END IF;

  -- Enqueue to target queue
  SELECT pgmq.send(
    v_queue_name,
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

-- 7. Claim next task function (target-specific claim)
CREATE OR REPLACE FUNCTION public.cvn_claim_next_task(
  p_worker_id TEXT,
  p_vt_seconds INT,
  p_target_agent TEXT
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
  v_queue_name TEXT;
BEGIN
  -- 1. Perform a cleanup pass on stale claims and old nonces
  PERFORM public.cvn_reap_stale_claims(5);
  DELETE FROM public.cvn_processed_nonces WHERE signed_at < now() - INTERVAL '5 minutes';

  -- Resolve queue name based on the worker's target agent
  IF p_target_agent = 'openclaw' THEN
    v_queue_name := 'cvn_tasks_queue_openclaw';
  ELSE
    v_queue_name := 'cvn_tasks_queue_hermes';
  END IF;

  -- 2. Read one message from the resolved PGMQ queue
  SELECT msg_id, message 
  FROM pgmq.read(v_queue_name, p_vt_seconds, 1) 
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
    PERFORM pgmq.delete(v_queue_name, v_msg_id);
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
    PERFORM pgmq.delete(v_queue_name, v_msg_id);
    RETURN QUERY SELECT 
      NULL::TEXT, 
      NULL::TEXT, 
      NULL::cvn_task_status, 
      NULL::JSONB, 
      FALSE;
    RETURN;
  END IF;

  -- Safeguard target mismatch: if the queue item does not match worker's capability,
  -- reset visibility and return false.
  IF (p_target_agent = 'openclaw' AND v_target_agent != 'openclaw') OR
     (p_target_agent = 'hermes' AND v_target_agent NOT IN ('hermes', 'auto')) THEN
    PERFORM pgmq.set_vt(v_queue_name, v_msg_id, 0);
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
      'queue_name', v_queue_name,
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

-- 8. Backward-compatible 2-argument wrapper for claim
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
BEGIN
  RETURN QUERY SELECT * FROM public.cvn_claim_next_task(p_worker_id, p_vt_seconds, 'hermes');
END;
$$;

-- 9. Complete task function (modified to support multiple queues)
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
  v_target_agent TEXT;
  v_queue_name TEXT;
BEGIN
  -- Lock task row
  SELECT status, claimed_by, queue_msg_id, target_agent
  FROM public.cvn_tasks
  WHERE public.cvn_tasks.task_id = p_task_id
  FOR UPDATE
  INTO v_status, v_claimed_by, v_msg_id, v_target_agent;

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

  -- Resolve queue name
  IF v_target_agent = 'openclaw' THEN
    v_queue_name := 'cvn_tasks_queue_openclaw';
  ELSE
    v_queue_name := 'cvn_tasks_queue_hermes';
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
    jsonb_build_object(
      'result_summary', p_result_summary,
      'queue_name', v_queue_name
    )
  );

  -- Archive from PGMQ queue
  IF v_msg_id IS NOT NULL THEN
    PERFORM pgmq.archive(v_queue_name, v_msg_id);
  END IF;

  RETURN QUERY SELECT TRUE, 'completed';
END;
$$;

-- 10. Fail task function with explicit dispositions
CREATE OR REPLACE FUNCTION public.cvn_fail_task(
  p_task_id TEXT,
  p_worker_id TEXT,
  p_error_message TEXT,
  p_error_code TEXT,
  p_disposition TEXT,
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
  v_target_agent TEXT;
  v_queue_name TEXT;
  v_new_status cvn_task_status;
  v_disposition TEXT;
BEGIN
  -- Lock task row
  SELECT public.cvn_tasks.status, public.cvn_tasks.claimed_by, public.cvn_tasks.retry_count, public.cvn_tasks.queue_msg_id, public.cvn_tasks.target_agent
  FROM public.cvn_tasks
  WHERE public.cvn_tasks.task_id = p_task_id
  FOR UPDATE
  INTO v_status, v_claimed_by, v_retry_count, v_msg_id, v_target_agent;

  IF v_status IS NULL THEN
    RETURN QUERY SELECT FALSE, NULL::cvn_task_status, NULL::INT;
    RETURN;
  END IF;

  -- Idempotency for terminal and manual review states
  IF v_status IN ('completed', 'cancelled', 'dead_letter', 'manual_review') THEN
    RETURN QUERY SELECT TRUE, v_status, v_retry_count;
    RETURN;
  END IF;

  -- Prevent worker collision
  IF v_claimed_by IS DISTINCT FROM p_worker_id THEN
    RETURN QUERY SELECT FALSE, v_status, v_retry_count;
    RETURN;
  END IF;

  -- Resolve queue name
  IF v_target_agent = 'openclaw' THEN
    v_queue_name := 'cvn_tasks_queue_openclaw';
  ELSE
    v_queue_name := 'cvn_tasks_queue_hermes';
  END IF;

  v_disposition := COALESCE(p_disposition, 'retryable');

  IF v_disposition = 'retryable' THEN
    v_retry_count := v_retry_count + 1;

    IF v_retry_count < p_max_retries THEN
      v_new_status := 'pending';
      
      UPDATE public.cvn_tasks
      SET 
        status = v_new_status,
        retry_count = v_retry_count,
        failed_at = now(),
        error_message = p_error_message,
        error_code = p_error_code,
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
          'error_code', p_error_code,
          'retry_count', v_retry_count,
          'action', 'requeued',
          'queue_name', v_queue_name
        )
      );

      IF v_msg_id IS NOT NULL THEN
        PERFORM pgmq.set_vt(v_queue_name, v_msg_id, 0);
      END IF;

    ELSE
      v_new_status := 'dead_letter';

      UPDATE public.cvn_tasks
      SET 
        status = v_new_status,
        retry_count = v_retry_count,
        failed_at = now(),
        error_message = p_error_message,
        error_code = p_error_code,
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
          'error_code', p_error_code,
          'retry_count', v_retry_count,
          'action', 'dead_letter',
          'queue_name', v_queue_name
        )
      );

      IF v_msg_id IS NOT NULL THEN
        PERFORM pgmq.delete(v_queue_name, v_msg_id);
      END IF;
    END IF;

  ELSIF v_disposition = 'permanent' THEN
    v_new_status := 'dead_letter';

    UPDATE public.cvn_tasks
    SET 
      status = v_new_status,
      failed_at = now(),
      error_message = p_error_message,
      error_code = p_error_code,
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
        'error_code', p_error_code,
        'action', 'permanent_failure',
        'queue_name', v_queue_name
      )
    );

    IF v_msg_id IS NOT NULL THEN
      PERFORM pgmq.delete(v_queue_name, v_msg_id);
    END IF;

  ELSIF v_disposition = 'execution_unknown' THEN
    v_new_status := 'manual_review';

    UPDATE public.cvn_tasks
    SET 
      status = v_new_status,
      failed_at = now(),
      error_message = p_error_message,
      error_code = p_error_code,
      claimed_by = NULL,
      claimed_at = NULL,
      expires_at = NULL,
      queue_msg_id = NULL
    WHERE public.cvn_tasks.task_id = p_task_id;

    INSERT INTO public.cvn_task_events (
      task_id, event_type, actor, metadata
    ) VALUES (
      p_task_id,
      'manual_review',
      p_worker_id,
      jsonb_build_object(
        'error_message', p_error_message,
        'error_code', p_error_code,
        'action', 'manual_review_needed',
        'queue_name', v_queue_name
      )
    );

    IF v_msg_id IS NOT NULL THEN
      PERFORM pgmq.delete(v_queue_name, v_msg_id);
    END IF;

  ELSE
    RAISE EXCEPTION 'Invalid failure disposition: %', v_disposition USING ERRCODE = '22023';
  END IF;

  RETURN QUERY SELECT TRUE, v_new_status, v_retry_count;
END;
$$;

-- 11. Backward-compatible 4-argument wrapper for fail task
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
BEGIN
  RETURN QUERY SELECT * FROM public.cvn_fail_task(
    p_task_id, p_worker_id, p_error_message, 'LEGACY_ERROR', 'retryable', p_max_retries
  );
END;
$$;

-- 12. Permissions and Grants
REVOKE EXECUTE ON FUNCTION public.cvn_claim_next_task(TEXT, INT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_claim_next_task(TEXT, INT, TEXT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_claim_next_task(TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_claim_next_task(TEXT, INT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, TEXT, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, TEXT, TEXT, INT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, INT) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_submit_task(TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT[], JSONB, TEXT, TEXT, TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_submit_task(TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT[], JSONB, TEXT, TEXT, TIMESTAMPTZ) TO service_role;

COMMIT;
