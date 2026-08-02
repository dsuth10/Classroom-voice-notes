-- 018_cvn_outbound_remediation_v2.sql
-- Forward migration for Step 6: Single lease-based RPC contract, mandatory delivery identity, full immutability enforcement, and hex check constraints.

BEGIN;

-- 1. Ensure tracking columns lease_token and lease_expires_at exist
ALTER TABLE public.cvn_outbound_items
    ADD COLUMN IF NOT EXISTS lease_token TEXT,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claimed_by_worker_id TEXT,
    ADD COLUMN IF NOT EXISTS delivery_attempts INT NOT NULL DEFAULT 0;

-- 2. Hex check constraints on payload_hash and content_hash
ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT IF EXISTS check_outbound_payload_hash_hex;
ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT check_outbound_payload_hash_hex CHECK (payload_hash ~ '^[0-9a-f]{64}$');

ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT IF EXISTS check_outbound_content_hash_hex;
ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT check_outbound_content_hash_hex CHECK (content_hash ~ '^[0-9a-f]{64}$');

-- 3. Immutability Trigger Function protecting ALL authoritative columns using IS DISTINCT FROM
CREATE OR REPLACE FUNCTION public.cvn_prevent_outbound_item_immutability_violation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
       NEW.payload_hash IS DISTINCT FROM OLD.payload_hash OR
       NEW.payload_json IS DISTINCT FROM OLD.payload_json OR
       NEW.source_device_id IS DISTINCT FROM OLD.source_device_id OR
       NEW.item_kind IS DISTINCT FROM OLD.item_kind OR
       NEW.target_agent IS DISTINCT FROM OLD.target_agent OR
       NEW.release_basis IS DISTINCT FROM OLD.release_basis OR
       NEW.approved_at IS DISTINCT FROM OLD.approved_at OR
       NEW.automatic_classification IS DISTINCT FROM OLD.automatic_classification OR
       NEW.risk_level IS DISTINCT FROM OLD.risk_level OR
       NEW.policy_gate_version IS DISTINCT FROM OLD.policy_gate_version OR
       NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR
       NEW.nonce IS DISTINCT FROM OLD.nonce OR
       NEW.signed_at IS DISTINCT FROM OLD.signed_at THEN
        RAISE EXCEPTION 'immutable_column_violation: Cannot mutate immutable fields on cvn_outbound_items'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_outbound_item_immutability ON public.cvn_outbound_items;
CREATE TRIGGER trg_prevent_outbound_item_immutability
    BEFORE UPDATE ON public.cvn_outbound_items
    FOR EACH ROW
    EXECUTE FUNCTION public.cvn_prevent_outbound_item_immutability_violation();

-- 4. Explicitly DROP all obsolete RPC overloaded signatures
DROP FUNCTION IF EXISTS public.cvn_claim_outbound_item(text, integer, text[], text[]);
DROP FUNCTION IF EXISTS public.cvn_claim_outbound_item(text, integer, text[], text[], text);
DROP FUNCTION IF EXISTS public.cvn_claim_outbound_item(text, integer, text[], text[], text, text);

DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, jsonb);
DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, text, jsonb);
DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, jsonb, text, text);
DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, text, text, text, jsonb);

DROP FUNCTION IF EXISTS public.cvn_fail_outbound_item(text, text, text, boolean, integer);
DROP FUNCTION IF EXISTS public.cvn_fail_outbound_item(text, text, text, boolean, integer, text, text);
DROP FUNCTION IF EXISTS public.cvn_fail_outbound_item(text, text, text, text, boolean, integer);

-- 5. Canonical Claim RPC with server-generated lease token
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
    AND (p_allowed_kinds IS NULL OR item_kind = ANY(p_allowed_kinds))
    AND (p_allowed_agents IS NULL OR target_agent = ANY(p_allowed_agents))
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF v_item.item_id IS NULL THEN
        RETURN NULL;
    END IF;

    v_lease_token := 'cvn-lease-' || encode(gen_random_bytes(16), 'hex');
    v_lease_expires := now() + (p_visibility_timeout_seconds || ' seconds')::interval;

    UPDATE public.cvn_outbound_items
    SET status = 'claimed',
        claimed_by = p_worker_id,
        claimed_by_worker_id = p_worker_id,
        claimed_at = now(),
        lease_token = v_lease_token,
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
        'lease_token', v_lease_token,
        'lease_expires_at', v_lease_expires,
        'attempt_count', v_item.attempt_count + 1,
        'visibility_deadline', v_lease_expires
    );
END;
$$;

-- 6. Canonical Complete RPC requiring mandatory lease token and mandatory matching hashes
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
        RETURN jsonb_build_object('success', true, 'item_id', p_item_id, 'status', 'completed', 'already_completed', true);
    END IF;

    IF v_row.status NOT IN ('claimed', 'claiming', 'processing') OR (COALESCE(v_row.claimed_by_worker_id, v_row.claimed_by) IS DISTINCT FROM p_worker_id) THEN
        RAISE EXCEPTION 'invalid_claim_owner: item % is owned by % not %', p_item_id, COALESCE(v_row.claimed_by_worker_id, v_row.claimed_by), p_worker_id USING ERRCODE = '28000';
    END IF;

    IF v_row.lease_token IS DISTINCT FROM p_lease_token THEN
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
        result_json = COALESCE(p_result_json, result_json)
    WHERE item_id = p_item_id;

    RETURN jsonb_build_object(
        'success', true,
        'item_id', p_item_id,
        'status', 'completed'
    );
END;
$$;

-- 7. Canonical Fail RPC requiring mandatory lease token
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
    v_next_status TEXT;
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

    IF v_row.lease_token IS DISTINCT FROM p_lease_token THEN
        RAISE EXCEPTION 'invalid_lease_token: Provided lease token does not match active claim lease' USING ERRCODE = '28000';
    END IF;

    IF v_row.lease_expires_at IS NULL OR v_row.lease_expires_at < now() THEN
        RAISE EXCEPTION 'lease_expired: Claim lease has expired' USING ERRCODE = '22023';
    END IF;

    IF p_retryable AND v_row.attempt_count < p_max_attempts THEN
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
        'attempt_count', v_row.attempt_count,
        'max_attempts', p_max_attempts
    );
END;
$$;

-- 8. Precise GRANT and REVOKE statements for exact canonical parameter signatures
REVOKE ALL ON FUNCTION public.cvn_claim_outbound_item(text, integer, text[], text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_complete_outbound_item(text, text, text, text, text, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_fail_outbound_item(text, text, text, text, boolean, integer) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item(text, integer, text[], text[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item(text, text, text, text, text, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item(text, text, text, text, boolean, integer) TO service_role;

COMMIT;
