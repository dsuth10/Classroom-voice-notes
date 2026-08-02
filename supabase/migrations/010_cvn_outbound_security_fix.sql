-- 010_cvn_outbound_security_fix.sql
-- Forward fix for PR 3: Revoke direct RPC execution from public/anon/authenticated,
-- enforce strict timestamp skew and schema validation, and fix cron scheduling.

BEGIN;

-- 1. Revoke public/anon/authenticated execution on cvn_submit_outbound_item
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;

REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM anon;

REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM authenticated;

-- 2. Restrict execution exclusively to service_role
GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO service_role;

-- 3. Replace stored procedure with hardened checks and safe search_path
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
SET search_path = public, pgmq, pg_temp
AS $$
DECLARE
    v_existing_id TEXT;
    v_existing_nonce TEXT;
    v_msg_id BIGINT;
BEGIN
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

-- 4. Re-schedule pg_cron job with safe dollar quoting
DO $block$
BEGIN
    PERFORM cron.unschedule('cvn-reap-outbound-items');
    PERFORM cron.schedule(
        'cvn-reap-outbound-items',
        '0 */12 * * *',
        $job$SELECT public.cvn_reap_outbound_dead_letters(30);$job$
    );
EXCEPTION WHEN OTHERS THEN NULL;
END $block$;

COMMIT;
