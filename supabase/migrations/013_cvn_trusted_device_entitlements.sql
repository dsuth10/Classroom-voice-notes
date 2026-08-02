-- 013_cvn_trusted_device_entitlements.sql
-- Service-role only entitlement table and evaluation RPC for server-authorized trusted device releases

BEGIN;

CREATE TABLE IF NOT EXISTS public.cvn_trusted_devices (
    client_key_id TEXT NOT NULL,
    source_device_id TEXT NOT NULL,
    environment TEXT NOT NULL DEFAULT 'staging',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_item_kinds TEXT[] NOT NULL DEFAULT '{record_only}',
    allowed_target_agents TEXT[] NOT NULL DEFAULT '{openclaw}',
    maximum_risk TEXT NOT NULL DEFAULT 'low',
    required_policy_version TEXT NOT NULL DEFAULT '2.0.0',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by TEXT,
    notes TEXT,
    PRIMARY KEY (client_key_id, source_device_id)
);

-- RLS: Enabled, default deny for anon/authenticated, full access for service_role only
ALTER TABLE public.cvn_trusted_devices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cvn_trusted_devices_service_role_all ON public.cvn_trusted_devices;
CREATE POLICY cvn_trusted_devices_service_role_all ON public.cvn_trusted_devices
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.cvn_trusted_devices FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.cvn_trusted_devices TO service_role;

-- Server RPC for evaluating trusted device entitlement
CREATE OR REPLACE FUNCTION public.cvn_evaluate_trusted_entitlement(
    p_client_key_id TEXT,
    p_source_device_id TEXT,
    p_environment TEXT DEFAULT 'staging',
    p_item_kind TEXT DEFAULT 'record_only',
    p_target_agent TEXT DEFAULT 'openclaw',
    p_risk_level TEXT DEFAULT 'low'
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row RECORD;
    v_risk_rank_req INT;
    v_risk_rank_max INT;
BEGIN
    SELECT * INTO v_row
    FROM public.cvn_trusted_devices
    WHERE client_key_id = p_client_key_id
      AND source_device_id = p_source_device_id;

    IF v_row.client_key_id IS NULL THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'entitlement_not_found',
            'error_message', format('No trusted device entitlement found for key %s and device %s.', p_client_key_id, p_source_device_id)
        );
    END IF;

    IF NOT v_row.enabled THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'entitlement_disabled',
            'error_message', 'Trusted device entitlement is disabled.'
        );
    END IF;

    IF v_row.expires_at IS NOT NULL AND v_row.expires_at <= NOW() THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'entitlement_expired',
            'error_message', 'Trusted device entitlement has expired.'
        );
    END IF;

    IF v_row.environment <> p_environment THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'environment_mismatch',
            'error_message', format('Entitlement environment (%s) does not match (%s).', v_row.environment, p_environment)
        );
    END IF;

    IF NOT (p_item_kind = ANY(v_row.allowed_item_kinds)) THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'item_kind_not_permitted',
            'error_message', format('Item kind %s is not permitted by entitlement.', p_item_kind)
        );
    END IF;

    IF NOT (p_target_agent = ANY(v_row.allowed_target_agents)) THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'target_agent_not_permitted',
            'error_message', format('Target agent %s is not permitted by entitlement.', p_target_agent)
        );
    END IF;

    -- Compare risk levels: low=1, medium=2, high=3
    v_risk_rank_req := CASE LOWER(p_risk_level) WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 4 END;
    v_risk_rank_max := CASE LOWER(v_row.maximum_risk) WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 0 END;

    IF v_risk_rank_req > v_risk_rank_max THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'risk_exceeds_maximum',
            'error_message', format('Item risk level (%s) exceeds entitlement maximum (%s).', p_risk_level, v_row.maximum_risk)
        );
    END IF;

    RETURN jsonb_build_object(
        'allowed', true,
        'reason_code', 'entitled',
        'entitlement', jsonb_build_object(
            'client_key_id', v_row.client_key_id,
            'source_device_id', v_row.source_device_id,
            'maximum_risk', v_row.maximum_risk,
            'required_policy_version', v_row.required_policy_version
        )
    );
END;
$$;

REVOKE ALL ON FUNCTION public.cvn_evaluate_trusted_entitlement FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_evaluate_trusted_entitlement TO service_role;

COMMIT;
