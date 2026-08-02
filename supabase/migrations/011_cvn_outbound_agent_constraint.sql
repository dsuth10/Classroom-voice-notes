-- 011_cvn_outbound_agent_constraint.sql
-- PR 5/7: Remove 'hermes' and 'auto' from target_agent constraint.
-- Only 'openclaw' is a registered v2 adapter. Hermes remains unregistered.
-- This is a forward-only migration. Rollback requires reverting constraint to
-- include hermes/auto (see comment below).

BEGIN;

-- Remove old constraint
ALTER TABLE public.cvn_outbound_items
    DROP CONSTRAINT IF EXISTS cvn_outbound_items_target_agent_check;

-- Add narrowed constraint
ALTER TABLE public.cvn_outbound_items
    ADD CONSTRAINT cvn_outbound_items_target_agent_check
    CHECK (target_agent IN ('openclaw'));

-- Validate: existing rows with hermes/auto will fail and must be manually reviewed.
-- In staging (no real rows), this is safe. In production, run:
--   SELECT item_id, target_agent FROM public.cvn_outbound_items
--   WHERE target_agent NOT IN ('openclaw')
-- before applying this migration.

-- Update cvn_submit_outbound_item to enforce openclaw-only at procedure boundary
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
SET search_path = public, pgmq
AS $$
DECLARE
    v_existing_id TEXT;
    v_existing_nonce TEXT;
    v_msg_id BIGINT;
BEGIN
    -- 0. Target agent allowlist
    IF p_target_agent NOT IN ('openclaw') THEN
        RAISE EXCEPTION 'unsupported_target_agent: %. Only openclaw is registered.', p_target_agent
            USING ERRCODE = '22023';
    END IF;

    -- 1. Idempotency Check
    SELECT item_id INTO v_existing_id
    FROM public.cvn_outbound_items
    WHERE idempotency_key = p_idempotency_key;

    IF v_existing_id IS NOT NULL THEN
        RAISE EXCEPTION 'duplicate_idempotency_key: %', p_idempotency_key
            USING ERRCODE = '23505';
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
    ELSIF p_release_basis IN ('human_approval', 'trusted_mode') THEN
        IF p_approved_at IS NULL THEN
            RAISE EXCEPTION 'invalid_release_basis: % requires approved_at timestamp', p_release_basis
                USING ERRCODE = '23514';
        END IF;
    ELSIF p_release_basis IS NULL OR p_release_basis NOT IN ('automatic_policy', 'human_approval', 'trusted_mode') THEN
        RAISE EXCEPTION 'invalid_release_basis: must be automatic_policy, human_approval, or trusted_mode'
            USING ERRCODE = '23514';
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

    -- 7. Enqueue into PGMQ
    SELECT * INTO v_msg_id FROM pgmq.send(
        queue_name := 'q_cvn_outbound_queue',
        msg := jsonb_build_object('item_id', p_item_id, 'item_kind', p_item_kind, 'target_agent', p_target_agent)
    );

    RETURN jsonb_build_object(
        'accepted', true,
        'item_id', p_item_id,
        'status', 'submitted',
        'msg_id', v_msg_id
    );
END;
$$;

-- Revoke/grant remain unchanged
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC;
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM anon;
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role;

-- Rollback notes:
-- To roll back to hermes/auto support:
--   ALTER TABLE public.cvn_outbound_items DROP CONSTRAINT cvn_outbound_items_target_agent_check;
--   ALTER TABLE public.cvn_outbound_items ADD CONSTRAINT cvn_outbound_items_target_agent_check CHECK (target_agent IN ('hermes', 'openclaw', 'auto'));
-- And revert this function to migration 010 version.

COMMIT;
