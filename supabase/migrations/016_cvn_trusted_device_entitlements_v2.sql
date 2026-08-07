-- 016_cvn_trusted_device_entitlements_v2.sql
-- Forward migration to enforce server-bound trusted device entitlements with environment unique identity and policy version checks.

BEGIN;

-- Update cvn_trusted_devices table to include environment in primary key and enforce strict column constraints
ALTER TABLE public.cvn_trusted_devices DROP CONSTRAINT IF EXISTS cvn_trusted_devices_pkey;
ALTER TABLE public.cvn_trusted_devices ADD PRIMARY KEY (client_key_id, source_device_id, environment);

ALTER TABLE public.cvn_trusted_devices DROP CONSTRAINT IF EXISTS check_maximum_risk;
ALTER TABLE public.cvn_trusted_devices ADD CONSTRAINT check_maximum_risk CHECK (maximum_risk IN ('low', 'medium', 'high'));

ALTER TABLE public.cvn_trusted_devices DROP CONSTRAINT IF EXISTS check_allowed_item_kinds_nonempty;
ALTER TABLE public.cvn_trusted_devices ADD CONSTRAINT check_allowed_item_kinds_nonempty CHECK (cardinality(allowed_item_kinds) > 0);

ALTER TABLE public.cvn_trusted_devices DROP CONSTRAINT IF EXISTS check_allowed_target_agents_nonempty;
ALTER TABLE public.cvn_trusted_devices ADD CONSTRAINT check_allowed_target_agents_nonempty CHECK (cardinality(allowed_target_agents) > 0);

ALTER TABLE public.cvn_trusted_devices DROP CONSTRAINT IF EXISTS check_environment_valid;
ALTER TABLE public.cvn_trusted_devices ADD CONSTRAINT check_environment_valid CHECK (environment IN ('staging', 'production'));

-- Updated RPC: cvn_evaluate_trusted_entitlement with required_policy_version checking and safe error reason codes
DROP FUNCTION IF EXISTS public.cvn_evaluate_trusted_entitlement(text, text, text, text, text, text);

CREATE OR REPLACE FUNCTION public.cvn_evaluate_trusted_entitlement(
    p_client_key_id TEXT,
    p_source_device_id TEXT,
    p_environment TEXT DEFAULT 'staging',
    p_item_kind TEXT DEFAULT 'record_only',
    p_target_agent TEXT DEFAULT 'openclaw',
    p_risk_level TEXT DEFAULT 'low',
    p_policy_version TEXT DEFAULT '2.0.0'
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
      AND source_device_id = p_source_device_id
      AND environment = p_environment;

    IF v_row.client_key_id IS NULL THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'entitlement_not_found',
            'error_message', 'Trusted device entitlement not found.'
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
            'error_message', 'Entitlement environment mismatch.'
        );
    END IF;

    IF v_row.required_policy_version IS NOT NULL AND v_row.required_policy_version <> p_policy_version THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'policy_version_mismatch',
            'error_message', 'Submitted policy version does not match required policy version.'
        );
    END IF;

    IF NOT (p_item_kind = ANY(v_row.allowed_item_kinds)) THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'item_kind_not_permitted',
            'error_message', 'Item kind is not permitted by entitlement.'
        );
    END IF;

    IF NOT (p_target_agent = ANY(v_row.allowed_target_agents)) THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'target_agent_not_permitted',
            'error_message', 'Target agent is not permitted by entitlement.'
        );
    END IF;

    -- Compare risk levels: low=1, medium=2, high=3
    v_risk_rank_req := CASE LOWER(p_risk_level) WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 4 END;
    v_risk_rank_max := CASE LOWER(v_row.maximum_risk) WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 0 END;

    IF v_risk_rank_req > v_risk_rank_max THEN
        RETURN jsonb_build_object(
            'allowed', false,
            'reason_code', 'risk_exceeds_maximum',
            'error_message', 'Item risk level exceeds entitlement maximum.'
        );
    END IF;

    RETURN jsonb_build_object(
        'allowed', true,
        'reason_code', 'entitled',
        'entitlement', jsonb_build_object(
            'client_key_id', v_row.client_key_id,
            'source_device_id', v_row.source_device_id,
            'environment', v_row.environment,
            'maximum_risk', v_row.maximum_risk,
            'required_policy_version', v_row.required_policy_version
        )
    );
END;
$$;

REVOKE ALL ON FUNCTION public.cvn_evaluate_trusted_entitlement FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_evaluate_trusted_entitlement TO service_role;

COMMIT;
