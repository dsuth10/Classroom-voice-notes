-- supabase/migrations/019_cvn_outbound_remediation_v3.sql
-- Migration 019: Atomic request nonce replay protection table and RPC for Edge Functions

CREATE TABLE IF NOT EXISTS public.cvn_request_nonces (
    credential_type text NOT NULL,
    key_id text NOT NULL,
    nonce text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (credential_type, key_id, nonce)
);

CREATE INDEX IF NOT EXISTS idx_cvn_request_nonces_expires_at
    ON public.cvn_request_nonces (expires_at);

GRANT ALL ON public.cvn_request_nonces TO service_role;

-- Atomic Nonce Registration RPC
CREATE OR REPLACE FUNCTION public.cvn_register_request_nonce(
    p_credential_type text,
    p_key_id text,
    p_nonce text,
    p_timestamp bigint,
    p_ttl_seconds integer DEFAULT 300
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_now_epoch bigint;
    v_expires_at timestamptz;
BEGIN
    -- Input validation sanity checks
    IF p_credential_type NOT IN ('worker', 'client') THEN
        RETURN false;
    END IF;
    IF p_key_id IS NULL OR length(p_key_id) > 64 OR p_key_id !~ '^[a-zA-Z0-9_-]+$' THEN
        RETURN false;
    END IF;
    IF p_nonce IS NULL OR length(p_nonce) < 8 OR length(p_nonce) > 128 THEN
        RETURN false;
    END IF;
    IF p_ttl_seconds IS NULL OR p_ttl_seconds < 30 OR p_ttl_seconds > 900 THEN
        RETURN false;
    END IF;

    v_now_epoch := extract(epoch from now())::bigint;

    -- Enforce timestamp window check (clock drift tolerance)
    IF abs(v_now_epoch - p_timestamp) > p_ttl_seconds THEN
        RETURN false;
    END IF;

    v_expires_at := now() + (p_ttl_seconds || ' seconds')::interval;

    -- Prune expired nonces
    DELETE FROM public.cvn_request_nonces
    WHERE expires_at < now();

    -- Atomic insert with conflict detection
    INSERT INTO public.cvn_request_nonces (credential_type, key_id, nonce, expires_at)
    VALUES (p_credential_type, p_key_id, p_nonce, v_expires_at)
    ON CONFLICT (credential_type, key_id, nonce) DO NOTHING;

    RETURN FOUND;
END;
$$;

-- Hardened execution permissions: Revoke from PUBLIC, anon, authenticated; Grant exclusively to service_role
REVOKE ALL ON FUNCTION public.cvn_register_request_nonce(text, text, text, bigint, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_register_request_nonce(text, text, text, bigint, integer) TO service_role;
