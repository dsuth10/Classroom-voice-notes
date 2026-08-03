-- 020_cvn_lease_hash_and_idempotency.sql
-- Step 7: Lease Hashing, Backoff Retries, and Submission Idempotency in Forward Migration 020

BEGIN;

-- 1. Add new lifecycle tracking columns to cvn_outbound_items
ALTER TABLE public.cvn_outbound_items
    ADD COLUMN IF NOT EXISTS lease_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error_code TEXT,
    ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS result_reference TEXT;

-- Check constraint for lease_token_hash hex format (64-char hex SHA256)
ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT IF EXISTS check_outbound_lease_token_hash_hex;
ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT check_outbound_lease_token_hash_hex 
    CHECK (lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$');

-- 2. Migrate active plaintext lease claims to retryable state to avoid orphaned lockouts
UPDATE public.cvn_outbound_items
SET status = 'failed_retryable',
    next_attempt_at = now(),
    lease_token = NULL,
    lease_expires_at = NULL,
    visibility_deadline = NULL
WHERE status IN ('claimed', 'claiming', 'processing')
  AND lease_token_hash IS NULL
  AND lease_token IS NOT NULL;

-- 3. Performance Index for Lease Eligibility
CREATE INDEX IF NOT EXISTS idx_cvn_outbound_items_claim_eligible
    ON public.cvn_outbound_items (status, next_attempt_at, created_at)
    WHERE status IN ('submitted', 'received', 'failed_retryable');

-- 4. Update cvn_submit_outbound_item with Exact Idempotency Matching vs Conflict
CREATE OR REPLACE FUNCTION public.cvn_submit_outbound_item(
    p_item_id TEXT,
    p_source_device_id TEXT,
    p_item_kind TEXT,
    p_target_agent TEXT,
    p_payload_json JSONB,
    p_payload_hash TEXT,
    p_content_hash TEXT,
    p_automatic_classification TEXT,
    p_risk_level TEXT,
    p_release_basis TEXT,
    p_approved_at TIMESTAMPTZ,
    p_policy_gate_version TEXT,
    p_idempotency_key TEXT,
    p_nonce TEXT,
    p_signed_at TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_existing_id TEXT;
    v_existing_content_hash TEXT;
    v_existing_status TEXT;
    v_existing_nonce TEXT;
BEGIN
    -- 1. Idempotency Check (exact match returns existing accepted status; mismatch raises conflict)
    SELECT item_id, content_hash, status INTO v_existing_id, v_existing_content_hash, v_existing_status
    FROM public.cvn_outbound_items
    WHERE idempotency_key = p_idempotency_key;

    IF v_existing_id IS NOT NULL THEN
        IF v_existing_id = p_item_id AND v_existing_content_hash = p_content_hash THEN
            RETURN jsonb_build_object(
                'accepted', true,
                'item_id', v_existing_id,
                'status', v_existing_status,
                'idempotent_replay', true
            );
        ELSE
            RAISE EXCEPTION 'idempotency_conflict: key % already used for item %', p_idempotency_key, v_existing_id
                USING ERRCODE = '23505';
        END IF;
    END IF;

    -- 2. Nonce Replay Check
    SELECT nonce INTO v_existing_nonce
    FROM public.cvn_outbound_items
    WHERE source_device_id = p_source_device_id AND nonce = p_nonce;

    IF v_existing_nonce IS NOT NULL THEN
        RAISE EXCEPTION 'nonce_replayed: %', p_nonce
            USING ERRCODE = '23505';
    END IF;

    -- 3. Stale / Future Timestamp Check (5 min limit)
    IF p_signed_at < (now() - INTERVAL '5 minutes') OR p_signed_at > (now() + INTERVAL '5 minutes') THEN
        RAISE EXCEPTION 'timestamp_skew: signed_at must be within 5 minutes of server time'
            USING ERRCODE = '22007';
    END IF;

    -- 3b. Schema Version Check
    IF (p_payload_json->>'schema_version') <> 'cvn.outbound_item.v2' THEN
        RAISE EXCEPTION 'invalid_schema_version: expected cvn.outbound_item.v2'
            USING ERRCODE = '22023';
    END IF;

    -- 4. Release Basis Validation Constraints
    IF p_release_basis = 'automatic_policy' THEN
        IF p_automatic_classification <> 'non_sensitive' OR p_risk_level <> 'low' THEN
            RAISE EXCEPTION 'invalid_release_basis: automatic_policy requires non_sensitive classification and low risk'
                USING ERRCODE = '23514';
        END IF;
    ELSIF p_release_basis = 'human_approval' THEN
        IF p_approved_at IS NULL THEN
            RAISE EXCEPTION 'invalid_release_basis: human_approval requires approved_at timestamp'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    -- 5. Record-Only Validation Constraint
    IF p_item_kind = 'record_only' THEN
        IF p_payload_json->'task' IS NOT NULL AND p_payload_json->'task' <> 'null'::jsonb THEN
            RAISE EXCEPTION 'invalid_item_kind: record_only items cannot contain executable task instructions'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    -- 6. Insert Into cvn_outbound_items Table
    INSERT INTO public.cvn_outbound_items (
        item_id, source_device_id, item_kind, target_agent, status,
        payload_json, payload_hash, content_hash, automatic_classification,
        risk_level, release_basis, approved_at, policy_gate_version,
        idempotency_key, nonce, signed_at
    ) VALUES (
        p_item_id, p_source_device_id, p_item_kind, p_target_agent, 'submitted',
        p_payload_json, p_payload_hash, p_content_hash, p_automatic_classification,
        p_risk_level, p_release_basis, p_approved_at, p_policy_gate_version,
        p_idempotency_key, p_nonce, p_signed_at
    );

    RETURN jsonb_build_object(
        'accepted', true,
        'item_id', p_item_id,
        'status', 'submitted'
    );
END;
$$;

-- 5. Update cvn_claim_outbound_item with Server-Side Hashed Lease & next_attempt_at Checking
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
    v_lease_token TEXT;
    v_lease_token_hash TEXT;
    v_lease_expires TIMESTAMPTZ;
BEGIN
    IF p_worker_id IS NULL OR trim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'missing_worker_id: Worker ID is required to claim items' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_item
    FROM public.cvn_outbound_items
    WHERE (
        status IN ('submitted', 'received', 'failed_retryable')
        OR (status IN ('claimed', 'claiming') AND visibility_deadline IS NOT NULL AND visibility_deadline < now())
    )
    AND (next_attempt_at IS NULL OR next_attempt_at <= now())
    AND (p_allowed_kinds IS NULL OR item_kind = ANY(p_allowed_kinds))
    AND (p_allowed_agents IS NULL OR target_agent = ANY(p_allowed_agents))
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF v_item.item_id IS NULL THEN
        RETURN NULL;
    END IF;

    -- Generate 256 bits (32 bytes) cryptographically secure random lease token
    v_lease_token := 'cvn-lease-' || encode(gen_random_bytes(32), 'hex');
    v_lease_token_hash := encode(sha256(convert_to(v_lease_token, 'UTF8')), 'hex');
    v_lease_expires := now() + (p_visibility_timeout_seconds || ' seconds')::interval;

    UPDATE public.cvn_outbound_items
    SET status = 'claimed',
        claimed_by = p_worker_id,
        claimed_by_worker_id = p_worker_id,
        claimed_at = now(),
        lease_token = NULL, -- do not store plaintext lease
        lease_token_hash = v_lease_token_hash,
        lease_expires_at = v_lease_expires,
        visibility_deadline = v_lease_expires,
        attempt_count = attempt_count + 1,
        delivery_attempts = delivery_attempts + 1
    WHERE item_id = v_item.item_id;

    RETURN jsonb_build_object(
        'claimed', true,
        'item_id', v_item.item_id,
        'item_kind', v_item.item_kind,
        'target_agent', v_item.target_agent,
        'payload_json', v_item.payload_json,
        'content_hash', v_item.content_hash,
        'payload_hash', v_item.payload_hash,
        'lease_token', v_lease_token, -- returned once in plaintext
        'lease_expires_at', v_lease_expires,
        'attempt_count', v_item.attempt_count + 1,
        'visibility_deadline', v_lease_expires
    );
END;
$$;

-- 6. Update cvn_complete_outbound_item with Hashed Lease Verification & Ownership Clearing
CREATE OR REPLACE FUNCTION public.cvn_complete_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_lease_token TEXT,
    p_payload_hash TEXT,
    p_content_hash TEXT,
    p_result_json JSONB DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
    v_given_lease_hash TEXT;
BEGIN
    IF p_item_id IS NULL OR trim(p_item_id) = '' THEN
        RAISE EXCEPTION 'missing_item_id: item_id is required' USING ERRCODE = '22023';
    END IF;
    IF p_worker_id IS NULL OR trim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'missing_worker_id: worker_id is required' USING ERRCODE = '22023';
    END IF;
    IF p_lease_token IS NULL OR trim(p_lease_token) = '' THEN
        RAISE EXCEPTION 'missing_lease_token: lease_token is required' USING ERRCODE = '22023';
    END IF;
    IF p_payload_hash IS NULL OR trim(p_payload_hash) = '' THEN
        RAISE EXCEPTION 'missing_payload_hash: payload_hash is required' USING ERRCODE = '22023';
    END IF;
    IF p_content_hash IS NULL OR trim(p_content_hash) = '' THEN
        RAISE EXCEPTION 'missing_content_hash: content_hash is required' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_row
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id
    FOR UPDATE;

    IF v_row.item_id IS NULL THEN
        RAISE EXCEPTION 'item_not_found: %', p_item_id USING ERRCODE = 'P0002';
    END IF;

    IF v_row.status = 'completed' THEN
        IF v_row.content_hash = p_content_hash AND v_row.payload_hash = p_payload_hash THEN
            RETURN jsonb_build_object('success', true, 'item_id', p_item_id, 'status', 'completed', 'already_completed', true);
        ELSE
            RAISE EXCEPTION 'completion_conflict: content or payload hash mismatch on already completed item' USING ERRCODE = '22023';
        END IF;
    END IF;

    IF v_row.status NOT IN ('claimed', 'claiming', 'processing') OR (COALESCE(v_row.claimed_by_worker_id, v_row.claimed_by) IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, COALESCE(v_row.claimed_by_worker_id, v_row.claimed_by), p_worker_id USING ERRCODE = '28000';
    END IF;

    -- Validate lease token via SHA256 digest
    v_given_lease_hash := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');

    IF (v_row.lease_token_hash IS NOT NULL AND v_row.lease_token_hash IS DISTINCT FROM v_given_lease_hash)
       OR (v_row.lease_token_hash IS NULL AND v_row.lease_token IS DISTINCT FROM p_lease_token) THEN
        RAISE EXCEPTION 'invalid_lease_token: Provided lease token does not match active claim lease' USING ERRCODE = '28000';
    END IF;

    IF v_row.lease_expires_at IS NULL OR v_row.lease_expires_at < now() THEN
        RAISE EXCEPTION 'lease_expired: Claim lease has expired' USING ERRCODE = '22023';
    END IF;

    IF p_content_hash <> v_row.content_hash THEN
        RAISE EXCEPTION 'content_hash_mismatch: Provided content hash does not match item content_hash' USING ERRCODE = '22023';
    END IF;

    IF p_payload_hash <> v_row.payload_hash THEN
        RAISE EXCEPTION 'payload_hash_mismatch: Provided payload hash does not match item payload_hash' USING ERRCODE = '22023';
    END IF;

    UPDATE public.cvn_outbound_items
    SET status = 'completed',
        completed_at = now(),
        result_json = COALESCE(p_result_json, result_json),
        lease_token = NULL,
        lease_token_hash = NULL,
        lease_expires_at = NULL,
        visibility_deadline = NULL
    WHERE item_id = p_item_id;

    RETURN jsonb_build_object(
        'success', true,
        'item_id', p_item_id,
        'status', 'completed'
    );
END;
$$;

-- 7. Update cvn_fail_outbound_item with Hashed Lease & Exponential Backoff Calculation
CREATE OR REPLACE FUNCTION public.cvn_fail_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_lease_token TEXT,
    p_failure_reason TEXT,
    p_retryable BOOLEAN DEFAULT TRUE,
    p_max_attempts INT DEFAULT 3
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
    v_given_lease_hash TEXT;
    v_next_status TEXT;
    v_backoff_seconds INT;
    v_next_attempt_at TIMESTAMPTZ;
BEGIN
    IF p_item_id IS NULL OR trim(p_item_id) = '' THEN
        RAISE EXCEPTION 'missing_item_id: item_id is required' USING ERRCODE = '22023';
    END IF;
    IF p_worker_id IS NULL OR trim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'missing_worker_id: worker_id is required' USING ERRCODE = '22023';
    END IF;
    IF p_lease_token IS NULL OR trim(p_lease_token) = '' THEN
        RAISE EXCEPTION 'missing_lease_token: lease_token is required' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_row
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id
    FOR UPDATE;

    IF v_row.item_id IS NULL THEN
        RAISE EXCEPTION 'item_not_found: %', p_item_id USING ERRCODE = 'P0002';
    END IF;

    IF v_row.status NOT IN ('claimed', 'claiming', 'processing') OR (COALESCE(v_row.claimed_by_worker_id, v_row.claimed_by) IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, COALESCE(v_row.claimed_by_worker_id, v_row.claimed_by), p_worker_id USING ERRCODE = '28000';
    END IF;

    v_given_lease_hash := encode(sha256(convert_to(p_lease_token, 'UTF8')), 'hex');

    IF (v_row.lease_token_hash IS NOT NULL AND v_row.lease_token_hash IS DISTINCT FROM v_given_lease_hash)
       OR (v_row.lease_token_hash IS NULL AND v_row.lease_token IS DISTINCT FROM p_lease_token) THEN
        RAISE EXCEPTION 'invalid_lease_token: Provided lease token does not match active claim lease' USING ERRCODE = '28000';
    END IF;

    IF v_row.lease_expires_at IS NULL OR v_row.lease_expires_at < now() THEN
        RAISE EXCEPTION 'lease_expired: Claim lease has expired' USING ERRCODE = '22023';
    END IF;

    IF p_retryable AND v_row.attempt_count < p_max_attempts THEN
        v_next_status := 'failed_retryable';
        -- Server-controlled exponential backoff: 10 * (2 ^ (attempt_count - 1)) seconds, max 3600 seconds (1 hour)
        v_backoff_seconds := LEAST(3600, (10 * (2 ^ GREATEST(0, v_row.attempt_count - 1)))::INT);
        v_next_attempt_at := now() + (v_backoff_seconds || ' seconds')::INTERVAL;
    ELSE
        v_next_status := 'dead_letter';
        v_next_attempt_at := NULL;
    END IF;

    UPDATE public.cvn_outbound_items
    SET status = v_next_status,
        failed_at = now(),
        failure_reason = p_failure_reason,
        last_error_code = 'worker_failure',
        last_error_at = now(),
        next_attempt_at = v_next_attempt_at,
        lease_token = NULL,
        lease_token_hash = NULL,
        lease_expires_at = NULL,
        visibility_deadline = NULL
    WHERE item_id = p_item_id;

    RETURN jsonb_build_object(
        'success', true,
        'item_id', p_item_id,
        'status', v_next_status,
        'attempt_count', v_row.attempt_count,
        'max_attempts', p_max_attempts,
        'next_attempt_at', v_next_attempt_at
    );
END;
$$;

-- 8. Execution Permissions
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_claim_outbound_item(text, integer, text[], text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_complete_outbound_item(text, text, text, text, text, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_fail_outbound_item(text, text, text, text, boolean, integer) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item(text, integer, text[], text[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item(text, text, text, text, text, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item(text, text, text, text, boolean, integer) TO service_role;

COMMIT;
