-- 008_cvn_outbound_items.sql
-- Phase 3: Outbound Items Table, pgmq queue, security-definer procedure for v2 payloads

BEGIN;

-- ============================================================================
-- 1. PGMQ Queue
-- ============================================================================
SELECT pgmq.create('q_cvn_outbound_queue');

-- ============================================================================
-- 2. cvn_outbound_items — Table for v2 Outbound Items
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.cvn_outbound_items (
    item_id                   TEXT PRIMARY KEY,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_device_id          TEXT NOT NULL,
    item_kind                 TEXT NOT NULL CHECK (item_kind IN ('record_only', 'agent_task')),
    target_agent              TEXT NOT NULL CHECK (target_agent IN ('hermes', 'openclaw', 'auto')),
    status                    TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'claimed', 'completed', 'failed')),
    payload_json              JSONB NOT NULL,
    payload_hash              TEXT NOT NULL,
    content_hash              TEXT NOT NULL,
    automatic_classification   TEXT NOT NULL,
    risk_level                TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    release_basis             TEXT NOT NULL CHECK (release_basis IN ('automatic_policy', 'human_approval', 'trusted_mode')),
    approved_at               TIMESTAMPTZ,
    policy_gate_version      TEXT NOT NULL,
    idempotency_key           TEXT NOT NULL UNIQUE,
    nonce                     TEXT NOT NULL,
    signed_at                 TIMESTAMPTZ NOT NULL,
    claimed_by                TEXT,
    claimed_at                TIMESTAMPTZ,
    completed_at              TIMESTAMPTZ,
    failed_at                 TIMESTAMPTZ,
    failure_reason            TEXT,
    result_json               JSONB,
    CONSTRAINT cvn_outbound_source_nonce UNIQUE (source_device_id, nonce)
);

CREATE INDEX IF NOT EXISTS idx_cvn_outbound_status ON public.cvn_outbound_items(status);
CREATE INDEX IF NOT EXISTS idx_cvn_outbound_item_kind ON public.cvn_outbound_items(item_kind);
CREATE INDEX IF NOT EXISTS idx_cvn_outbound_target_agent ON public.cvn_outbound_items(target_agent);
CREATE INDEX IF NOT EXISTS idx_cvn_outbound_created_at ON public.cvn_outbound_items(created_at DESC);

-- ============================================================================
-- 3. Security Definer Stored Procedure for v2 Submission
-- ============================================================================
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

-- ============================================================================
-- 4. Enable RLS & Grants
-- ============================================================================
ALTER TABLE public.cvn_outbound_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_all_cvn_outbound ON public.cvn_outbound_items;
CREATE POLICY service_role_all_cvn_outbound ON public.cvn_outbound_items
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC;
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM anon;
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM authenticated;

GRANT ALL ON public.cvn_outbound_items TO service_role;
GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role;

COMMIT;
