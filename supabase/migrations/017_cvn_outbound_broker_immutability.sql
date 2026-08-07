-- 017_cvn_outbound_broker_immutability.sql
-- Forward migration for Step 6: Item column immutability trigger, worker target binding, content/payload hash verification on completion, and device-scoped status lookup.

BEGIN;

-- 1. Add missing tracking columns if not present
ALTER TABLE public.cvn_outbound_items
    ADD COLUMN IF NOT EXISTS claimed_by_worker_id TEXT,
    ADD COLUMN IF NOT EXISTS delivery_attempts INT NOT NULL DEFAULT 0;

-- 2. Add table check constraints for non-empty IDs, hash lengths, and valid timestamp ordering
ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT IF EXISTS check_outbound_non_empty_ids;
ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT check_outbound_non_empty_ids CHECK (length(trim(item_id)) > 0 AND length(trim(source_device_id)) > 0);

ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT IF EXISTS check_outbound_content_hash_length;
ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT check_outbound_content_hash_length CHECK (length(trim(content_hash)) = 64);

ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT IF EXISTS check_outbound_timestamp_order;
ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT check_outbound_timestamp_order CHECK (
    (claimed_at IS NULL OR claimed_at >= created_at) AND
    (completed_at IS NULL OR completed_at >= created_at) AND
    (failed_at IS NULL OR failed_at >= created_at)
);

-- 3. Immutability Trigger Function
CREATE OR REPLACE FUNCTION public.cvn_prevent_outbound_item_immutability_violation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.content_hash <> OLD.content_hash OR
       NEW.payload_hash <> OLD.payload_hash OR
       NEW.payload_json <> OLD.payload_json OR
       NEW.source_device_id <> OLD.source_device_id OR
       NEW.item_kind <> OLD.item_kind OR
       NEW.target_agent <> OLD.target_agent OR
       NEW.release_basis <> OLD.release_basis OR
       (NEW.approved_at IS DISTINCT FROM OLD.approved_at) THEN
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

-- 4. Worker Claim RPC with target_agent binding and safe worker payload return
DROP FUNCTION IF EXISTS public.cvn_claim_outbound_item(text, int, text[], text[], text);

CREATE OR REPLACE FUNCTION public.cvn_claim_outbound_item(
    p_worker_id TEXT,
    p_visibility_timeout_seconds INT DEFAULT 300,
    p_allowed_kinds TEXT[] DEFAULT NULL,
    p_allowed_agents TEXT[] DEFAULT NULL,
    p_target_agent TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pgmq
AS $$
DECLARE
    v_item RECORD;
    v_target TEXT;
BEGIN
    IF p_worker_id IS NULL OR trim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'missing_worker_id: Worker ID is required to claim items' USING ERRCODE = '22023';
    END IF;

    v_target := COALESCE(p_target_agent, (CASE WHEN p_allowed_agents IS NOT NULL AND array_length(p_allowed_agents, 1) > 0 THEN p_allowed_agents[1] ELSE 'openclaw' END));

    SELECT * INTO v_item
    FROM public.cvn_outbound_items
    WHERE (
        status IN ('submitted', 'received', 'failed_retryable')
        OR (status IN ('claimed', 'claiming') AND visibility_deadline IS NOT NULL AND visibility_deadline < now())
    )
    AND target_agent = v_target
    AND (p_allowed_kinds IS NULL OR item_kind = ANY(p_allowed_kinds))
    AND (p_allowed_agents IS NULL OR target_agent = ANY(p_allowed_agents))
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF v_item.item_id IS NULL THEN
        RETURN NULL;
    END IF;

    UPDATE public.cvn_outbound_items
    SET status = 'claimed',
        claimed_by = p_worker_id,
        claimed_by_worker_id = p_worker_id,
        claimed_at = now(),
        visibility_deadline = now() + (p_visibility_timeout_seconds || ' seconds')::interval,
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
        'attempt_count', v_item.attempt_count + 1,
        'visibility_deadline', now() + (p_visibility_timeout_seconds || ' seconds')::interval
    );
END;
$$;

-- 5. Complete RPC with Content/Payload Hash Match Verification
DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, jsonb);
DROP FUNCTION IF EXISTS public.cvn_complete_outbound_item(text, text, text, jsonb);

CREATE OR REPLACE FUNCTION public.cvn_complete_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_result_json JSONB DEFAULT NULL,
    p_content_hash TEXT DEFAULT NULL,
    p_payload_hash TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
BEGIN
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

    IF p_content_hash IS NOT NULL AND p_content_hash <> v_row.content_hash THEN
        RAISE EXCEPTION 'content_hash_mismatch: Provided content hash does not match item content_hash' USING ERRCODE = '22023';
    END IF;

    IF p_payload_hash IS NOT NULL AND p_payload_hash <> v_row.payload_hash THEN
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

-- 6. Fail RPC with Content/Payload Hash Match Verification
DROP FUNCTION IF EXISTS public.cvn_fail_outbound_item(text, text, text, boolean, int);
DROP FUNCTION IF EXISTS public.cvn_fail_outbound_item(text, text, text, text, boolean, int);

CREATE OR REPLACE FUNCTION public.cvn_fail_outbound_item(
    p_item_id TEXT,
    p_worker_id TEXT,
    p_failure_reason TEXT,
    p_retryable BOOLEAN DEFAULT TRUE,
    p_max_attempts INT DEFAULT 3,
    p_content_hash TEXT DEFAULT NULL,
    p_payload_hash TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
    v_next_status TEXT;
BEGIN
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

    IF p_content_hash IS NOT NULL AND p_content_hash <> v_row.content_hash THEN
        RAISE EXCEPTION 'content_hash_mismatch: Provided content hash does not match item content_hash' USING ERRCODE = '22023';
    END IF;

    IF p_payload_hash IS NOT NULL AND p_payload_hash <> v_row.payload_hash THEN
        RAISE EXCEPTION 'payload_hash_mismatch: Provided payload hash does not match item payload_hash' USING ERRCODE = '22023';
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

-- 7. Device-Scoped Status Lookup RPC
DROP FUNCTION IF EXISTS public.cvn_get_outbound_item_status(text);

CREATE OR REPLACE FUNCTION public.cvn_get_outbound_item_status(
    p_item_id TEXT,
    p_source_device_id TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
BEGIN
    SELECT item_id, source_device_id, status, item_kind, target_agent, created_at, claimed_at, completed_at, failed_at, failure_reason, attempt_count
    INTO v_row
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id;

    IF v_row.item_id IS NULL THEN
        RETURN jsonb_build_object('found', false, 'item_id', p_item_id);
    END IF;

    -- Device scope check: if p_source_device_id is provided, reject mismatched caller device
    IF p_source_device_id IS NOT NULL AND v_row.source_device_id <> p_source_device_id THEN
        RETURN jsonb_build_object('found', false, 'item_id', p_item_id, 'error', 'unauthorized_device');
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

-- 8. Revoke direct write access and re-grant SECURITY DEFINER execution to service_role only
REVOKE ALL ON public.cvn_outbound_items FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.cvn_outbound_items TO service_role;

REVOKE ALL ON FUNCTION public.cvn_claim_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_complete_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_fail_outbound_item FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cvn_get_outbound_item_status FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_get_outbound_item_status TO service_role;

COMMIT;
