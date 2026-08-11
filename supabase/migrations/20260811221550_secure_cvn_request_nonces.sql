-- Migration 022: Remove public Data API access from the request nonce table.
--
-- This table is internal replay-protection state. Only trusted server-side code
-- using the service role may access it; clients use the restricted
-- cvn_register_request_nonce RPC instead of accessing the table directly.

BEGIN;

ALTER TABLE public.cvn_request_nonces ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.cvn_request_nonces
FROM PUBLIC, anon, authenticated;

GRANT ALL ON TABLE public.cvn_request_nonces TO service_role;

DROP POLICY IF EXISTS cvn_request_nonces_service_all
ON public.cvn_request_nonces;

CREATE POLICY cvn_request_nonces_service_all
ON public.cvn_request_nonces
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

COMMIT;
