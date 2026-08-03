-- Migration 021: Drop overloaded status RPC signatures and establish single canonical status lookup RPC

DROP FUNCTION IF EXISTS public.cvn_get_outbound_item_status(TEXT);
DROP FUNCTION IF EXISTS public.cvn_get_outbound_item_status(TEXT, TEXT);

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
    SELECT item_id, source_device_id, status, item_kind, target_agent, claimed_by_worker_id, created_at, claimed_at, completed_at, failed_at, failure_reason, attempt_count, result_reference, lease_expires_at
    INTO v_row
    FROM public.cvn_outbound_items
    WHERE item_id = p_item_id;

    IF v_row.item_id IS NULL THEN
        RETURN jsonb_build_object('found', false, 'item_id', p_item_id);
    END IF;

    IF p_source_device_id IS NOT NULL AND v_row.source_device_id IS DISTINCT FROM p_source_device_id THEN
        RETURN jsonb_build_object('found', false, 'item_id', p_item_id, 'reason', 'device_mismatch');
    END IF;

    RETURN jsonb_build_object(
        'found', true,
        'item_id', v_row.item_id,
        'status', v_row.status,
        'item_kind', v_row.item_kind,
        'target_agent', v_row.target_agent,
        'claimed_by_worker_id', v_row.claimed_by_worker_id,
        'created_at', v_row.created_at,
        'claimed_at', v_row.claimed_at,
        'completed_at', v_row.completed_at,
        'failed_at', v_row.failed_at,
        'failure_reason', v_row.failure_reason,
        'attempt_count', v_row.attempt_count,
        'result_reference', v_row.result_reference,
        'lease_expires_at', v_row.lease_expires_at
    );
END;
$$;
