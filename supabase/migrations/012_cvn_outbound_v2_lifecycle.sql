-- 012_cvn_outbound_v2_lifecycle.sql
-- Database-backed v2 lifecycle: atomic claim with visibility timeout, complete, fail, retry, and status lookup

BEGIN;

-- 1. Extend cvn_outbound_items columns & status constraints
ALTER TABLE public.cvn_outbound_items
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS visibility_deadline TIMESTAMPTZ;

ALTER TABLE public.cvn_outbound_items
    DROP CONSTRAINT IF EXISTS cvn_outbound_items_status_check;

ALTER TABLE public.cvn_outbound_items
    ADD CONSTRAINT cvn_outbound_items_status_check
    CHECK (status IN ('submitted', 'claimed', 'completed', 'failed_retryable', 'failed_permanent', 'dead_letter', 'expired'));

-- 2. Atomic Claim RPC
CREATE OR REPLACE FUNCTION public.cvn_claim_outbound_item(
    p_worker_id TEXT,
    p_visibility_timeout_seconds INT DEFAULT 300,
    p_allowed_kinds TEXT[] DEFAULT NULL,
    p_allowed_agents TEXT[] DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
DECLARE
    v_item RECORD;
BEGIN
    -- Select first processable item: either 'submitted', 'failed_retryable', or expired 'claimed' lease
    SELECT * INTO v_item
    FROM public.cvn_outbound_items
    WHERE (
        status IN ('submitted', 'failed_retryable')
        OR (status = 'claimed' AND visibility_deadline IS NOT NULL AND visibility_deadline < now())
    )
    AND (p_allowed_kinds IS NULL OR item_kind = ANY(p_allowed_kinds))
    AND (p_allowed_agents IS NULL OR target_agent = ANY(p_allowed_agents))
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF v_item.item_id IS NULL THEN
        RETURN NULL;
    END IF;

    -- Update state atomically to claimed
    UPDATE public.cvn_outbound_items
    SET status = 'claimed',
        claimed_by = p_worker_id,
        claimed_at = now(),
        visibility_deadline = now() + (p_visibility_timeout_seconds || ' seconds')::interval,
        attempt_count = attempt_count + 1
    WHERE item_id = v_item.item_id;

    RETURN jsonb_build_object(
        'claimed', true,
        'item_id', v_item.item_id,
        'item_kind', v_item.item_kind,
        'target_agent', v_item.target_agent,
        'payload_json', v_item.payload_json,
        'attempt_count', v_item.attempt_count + 1,
        'visibility_deadline', now() + (p_visibility_timeout_seconds || ' seconds')::interval
    );
END;
$$;

-- 3. Atomic Complete RPC
CREATE OR REPLACE FUNCTION public.cvn_complete_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_result_json JSONB DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_current_status TEXT;
    v_claimed_by TEXT;
BEGIN
    SELECT status, claimed_by INTO v_current_status, v_claimed_by
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id
    FOR UPDATE;

    IF v_current_status IS NULL THEN
        RAISE EXCEPTION 'item_not_found: %', p_item_id USING ERRCODE = 'P0002';
    END IF;

    -- Idempotent completion if already completed
    IF v_current_status = 'completed' THEN
        RETURN jsonb_build_object('success', true, 'item_id', p_item_id, 'status', 'completed', 'already_completed', true);
    END IF;

    IF v_current_status <> 'claimed' OR (v_claimed_by IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, v_claimed_by, p_worker_id USING ERRCODE = '28000';
    END IF;

    UPDATE public.cvn_outbound_items
    SET status = 'completed',
        completed_at = now(),
        result_json = COALESCE(p_result_json, result_json)
    WHERE item_id = p_item_id;

    RETURN jsonb_build_object(
        'success', true,
        'item_id', p_item_id,
        'status', 'completed'
    );
END;
$$;

-- 4. Atomic Fail / Retry Disposition RPC
CREATE OR REPLACE FUNCTION public.cvn_fail_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_failure_reason TEXT,
    p_retryable BOOLEAN DEFAULT TRUE,
    p_max_attempts INT DEFAULT 3
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_current_status TEXT;
    v_claimed_by TEXT;
    v_attempts INT;
    v_next_status TEXT;
BEGIN
    SELECT status, claimed_by, attempt_count INTO v_current_status, v_claimed_by, v_attempts
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id
    FOR UPDATE;

    IF v_current_status IS NULL THEN
        RAISE EXCEPTION 'item_not_found: %', p_item_id USING ERRCODE = 'P0002';
    END IF;

    IF v_current_status <> 'claimed' OR (v_claimed_by IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, v_claimed_by, p_worker_id USING ERRCODE = '28000';
    END IF;

    IF p_retryable AND v_attempts < p_max_attempts THEN
        v_next_status := 'failed_retryable';
    ELSE
        v_next_status := 'dead_letter';
    END IF;

    UPDATE public.cvn_outbound_items
    SET status = v_next_status,
        failed_at = now(),
        failure_reason = p_failure_reason,
        visibility_deadline = NULL
    WHERE item_id = p_item_id;

    RETURN jsonb_build_object(
        'success', true,
        'item_id', p_item_id,
        'status', v_next_status,
        'attempt_count', v_attempts,
        'max_attempts', p_max_attempts
    );
END;
$$;

-- 5. Status Lookup RPC
CREATE OR REPLACE FUNCTION public.cvn_get_outbound_item_status(
    p_item_id TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
BEGIN
    SELECT item_id, status, item_kind, target_agent, created_at, claimed_at, completed_at, failed_at, failure_reason, attempt_count
    INTO v_row
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id;

    IF v_row.item_id IS NULL THEN
        RETURN jsonb_build_object('found', false, 'item_id', p_item_id);
    END IF;

    RETURN jsonb_build_object(
        'found', true,
        'item_id', v_row.item_id,
        'status', v_row.status,
        'item_kind', v_row.item_kind,
        'target_agent', v_row.target_agent,
        'created_at', v_row.created_at,
        'claimed_at', v_row.claimed_at,
        'completed_at', v_row.completed_at,
        'failed_at', v_row.failed_at,
        'failure_reason', v_row.failure_reason,
        'attempt_count', v_row.attempt_count
    );
END;
$$;

-- 6. Strict Security Definer Revocations & Grants
REVOKE ALL ON FUNCTION public.cvn_claim_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_complete_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_fail_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_get_outbound_item_status FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_get_outbound_item_status TO service_role;

COMMIT;
