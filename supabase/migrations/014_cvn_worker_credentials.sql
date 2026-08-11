-- 014_cvn_worker_credentials.sql
-- Worker credential isolation, lease token enforcement, and worker authentication RPCs

BEGIN;

-- 1. Add lease_token column to cvn_outbound_items
ALTER TABLE public.cvn_outbound_items
    ADD COLUMN IF NOT EXISTS lease_token TEXT;

-- 2. Worker credentials table (service-role only)
CREATE TABLE IF NOT EXISTS public.cvn_worker_credentials (
    worker_id TEXT PRIMARY KEY,
    secret_hash TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_item_kinds TEXT[] NOT NULL DEFAULT '{record_only}',
    allowed_target_agents TEXT[] NOT NULL DEFAULT '{openclaw}',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);

ALTER TABLE public.cvn_worker_credentials ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cvn_worker_credentials_service_role_all ON public.cvn_worker_credentials;
CREATE POLICY cvn_worker_credentials_service_role_all ON public.cvn_worker_credentials
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.cvn_worker_credentials FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.cvn_worker_credentials TO service_role;

-- 3. Worker credential verification RPC
CREATE OR REPLACE FUNCTION public.cvn_verify_worker_credential(
    p_worker_id TEXT,
    p_secret_hash TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
BEGIN
    SELECT * INTO v_row
    FROM public.cvn_worker_credentials
    WHERE worker_id = p_worker_id;

    IF v_row.worker_id IS NULL THEN
        RETURN jsonb_build_object(
            'valid', false,
            'reason_code', 'worker_not_found',
            'error_message', format('Worker ID %s not registered.', p_worker_id)
        );
    END IF;

    IF NOT v_row.enabled THEN
        RETURN jsonb_build_object(
            'valid', false,
            'reason_code', 'worker_disabled',
            'error_message', 'Worker credential is disabled.'
        );
    END IF;

    IF v_row.expires_at IS NOT NULL AND v_row.expires_at <= NOW() THEN
        RETURN jsonb_build_object(
            'valid', false,
            'reason_code', 'worker_expired',
            'error_message', 'Worker credential has expired.'
        );
    END IF;

    IF v_row.secret_hash <> p_secret_hash THEN
        RETURN jsonb_build_object(
            'valid', false,
            'reason_code', 'invalid_secret',
            'error_message', 'Worker secret verification failed.'
        );
    END IF;

    RETURN jsonb_build_object(
        'valid', true,
        'worker_id', v_row.worker_id,
        'allowed_item_kinds', v_row.allowed_item_kinds,
        'allowed_target_agents', v_row.allowed_target_agents
    );
END;
$$;

-- 4. Update Atomic Claim RPC with lease token generation
DROP FUNCTION IF EXISTS public.cvn_claim_outbound_item(text, int, text[], text[]);
DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, jsonb);
DROP FUNCTION IF EXISTS public.cvn_fail_outbound_item(text, text, text, boolean, int);

CREATE OR REPLACE FUNCTION public.cvn_claim_outbound_item(
    p_worker_id TEXT,
    p_visibility_timeout_seconds INT DEFAULT 300,
    p_allowed_kinds TEXT[] DEFAULT NULL,
    p_allowed_agents TEXT[] DEFAULT NULL,
    p_lease_token TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
DECLARE
    v_item RECORD;
    v_generated_lease TEXT;
BEGIN
    -- Select first processable item
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

    v_generated_lease := COALESCE(p_lease_token, 'CVNL-' || md5(random()::text || clock_timestamp()::text));

    -- Update state atomically to claimed with lease_token
    UPDATE public.cvn_outbound_items
    SET status = 'claimed',
        claimed_by = p_worker_id,
        claimed_at = now(),
        visibility_deadline = now() + (p_visibility_timeout_seconds || ' seconds')::interval,
        attempt_count = attempt_count + 1,
        lease_token = v_generated_lease
    WHERE item_id = v_item.item_id;

    RETURN jsonb_build_object(
        'claimed', true,
        'item_id', v_item.item_id,
        'item_kind', v_item.item_kind,
        'target_agent', v_item.target_agent,
        'payload_json', v_item.payload_json,
        'attempt_count', v_item.attempt_count + 1,
        'lease_token', v_generated_lease,
        'visibility_deadline', now() + (p_visibility_timeout_seconds || ' seconds')::interval
    );
END;
$$;

-- 5. Update Atomic Complete RPC with Lease Token Verification
CREATE OR REPLACE FUNCTION public.cvn_complete_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_lease_token TEXT DEFAULT NULL,
    p_result_json JSONB DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_current_status TEXT;
    v_claimed_by TEXT;
    v_current_lease TEXT;
BEGIN
    SELECT status, claimed_by, lease_token INTO v_current_status, v_claimed_by, v_current_lease
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id
    FOR UPDATE;

    IF v_current_status IS NULL THEN
        RAISE EXCEPTION 'item_not_found: %', p_item_id USING ERRCODE = 'P0002';
    END IF;

    IF v_current_status = 'completed' THEN
        RETURN jsonb_build_object('success', true, 'item_id', p_item_id, 'status', 'completed', 'already_completed', true);
    END IF;

    IF v_current_status <> 'claimed' OR (v_claimed_by IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, v_claimed_by, p_worker_id USING ERRCODE = '28000';
    END IF;

    IF p_lease_token IS NOT NULL AND v_current_lease IS DISTINCT FROM p_lease_token THEN
        RAISE EXCEPTION 'invalid_lease_token: item % lease token mismatch', p_item_id USING ERRCODE = '28000';
    END IF;

    UPDATE public.cvn_outbound_items
    SET status = 'completed',
        completed_at = now(),
        result_json = COALESCE(p_result_json, result_json),
        lease_token = NULL
    WHERE item_id = p_item_id;

    RETURN jsonb_build_object(
        'success', true,
        'item_id', p_item_id,
        'status', 'completed'
    );
END;
$$;

-- 6. Update Atomic Fail RPC with Lease Token Verification
CREATE OR REPLACE FUNCTION public.cvn_fail_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_failure_reason TEXT,
    p_lease_token TEXT DEFAULT NULL,
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
    v_current_lease TEXT;
    v_attempts INT;
    v_next_status TEXT;
BEGIN
    SELECT status, claimed_by, lease_token, attempt_count INTO v_current_status, v_claimed_by, v_current_lease, v_attempts
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id
    FOR UPDATE;

    IF v_current_status IS NULL THEN
        RAISE EXCEPTION 'item_not_found: %', p_item_id USING ERRCODE = 'P0002';
    END IF;

    IF v_current_status <> 'claimed' OR (v_claimed_by IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, v_claimed_by, p_worker_id USING ERRCODE = '28000';
    END IF;

    IF p_lease_token IS NOT NULL AND v_current_lease IS DISTINCT FROM p_lease_token THEN
        RAISE EXCEPTION 'invalid_lease_token: item % lease token mismatch', p_item_id USING ERRCODE = '28000';
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
        visibility_deadline = NULL,
        lease_token = NULL
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

-- 7. Grants & Revocations
REVOKE ALL ON FUNCTION public.cvn_verify_worker_credential FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_verify_worker_credential TO service_role;

REVOKE ALL ON FUNCTION public.cvn_claim_outbound_item FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item TO service_role;

REVOKE ALL ON FUNCTION public.cvn_complete_outbound_item FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item TO service_role;

REVOKE ALL ON FUNCTION public.cvn_fail_outbound_item FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item TO service_role;

COMMIT;
