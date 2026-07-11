BEGIN;

-- 1. Complete task function (modified for atomic target authorization)
CREATE OR REPLACE FUNCTION public.cvn_complete_task(
  p_task_id TEXT,
  p_worker_id TEXT,
  p_result_summary TEXT,
  p_allowed_targets TEXT[] DEFAULT NULL
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

  -- Atomic target authorization
  IF p_allowed_targets IS NOT NULL AND NOT (v_target_agent = ANY(p_allowed_targets)) THEN
    RETURN QUERY SELECT FALSE, 'unauthorized_target';
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

-- 2. Fail task function with explicit dispositions and atomic target authorization
CREATE OR REPLACE FUNCTION public.cvn_fail_task(
  p_task_id TEXT,
  p_worker_id TEXT,
  p_error_message TEXT,
  p_error_code TEXT,
  p_disposition TEXT,
  p_max_retries INT DEFAULT 5,
  p_allowed_targets TEXT[] DEFAULT NULL
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

  -- Atomic target authorization
  IF p_allowed_targets IS NOT NULL AND NOT (v_target_agent = ANY(p_allowed_targets)) THEN
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

-- 3. Backward-compatible 4-argument wrapper for fail task
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
    p_task_id, p_worker_id, p_error_message, 'LEGACY_ERROR', 'retryable', p_max_retries, NULL
  );
END;
$$;

-- 4. Permissions and Grants
REVOKE EXECUTE ON FUNCTION public.cvn_complete_task(TEXT, TEXT, TEXT, TEXT[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_complete_task(TEXT, TEXT, TEXT, TEXT[]) TO service_role;

REVOKE EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, TEXT, TEXT, INT, TEXT[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cvn_fail_task(TEXT, TEXT, TEXT, TEXT, TEXT, INT, TEXT[]) TO service_role;

COMMIT;
