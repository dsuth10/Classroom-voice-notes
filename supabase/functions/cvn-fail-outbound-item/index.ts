import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import {
  authenticateWorker,
  AuthenticationError,
} from "../_shared/broker_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-cvn-signature, x-cvn-key-id, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

serve(async (req: Request) => {
  if (req.method === "OPTIONS")
    return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method_not_allowed" }), {
      status: 405,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const bodyText = await req.text();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  let authWorker;
  try {
    authWorker = await authenticateWorker(req, bodyText, supabase);
  } catch (authErr) {
    return new Response(
      JSON.stringify({
        error: "unauthorized",
        message:
          authErr instanceof AuthenticationError
            ? authErr.message
            : "Worker authentication failed",
      }),
      {
        status: 401,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  let body: any = {};
  try {
    if (bodyText) body = JSON.parse(bodyText);
  } catch (_e) {
    return new Response(JSON.stringify({ error: "invalid_json" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const itemId = body.item_id;
  const requestedWorkerId = body.worker_id;
  let workerId: string;
  if (requestedWorkerId) {
    if (
      authWorker.allowed_worker_ids.length > 0 &&
      !authWorker.allowed_worker_ids.includes(requestedWorkerId)
    ) {
      return new Response(
        JSON.stringify({
          error: "worker_identity_unauthorized",
          message: `Worker key is not authorized for worker_id '${requestedWorkerId}'`,
        }),
        {
          status: 403,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }
    workerId = requestedWorkerId;
  } else {
    workerId = authWorker.allowed_worker_ids[0] || authWorker.key_id;
  }
  const leaseToken = body.lease_token;

  if (!itemId || !leaseToken) {
    return new Response(
      JSON.stringify({
        error: "missing_required_fail_fields",
        message: "item_id and lease_token are mandatory",
      }),
      {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const { data, error } = await supabase.rpc("cvn_fail_outbound_item", {
    p_item_id: itemId,
    p_worker_id: workerId,
    p_lease_token: leaseToken,
    p_failure_reason: body.failure_reason ?? "unknown_failure",
    p_retryable: body.retryable ?? true,
    p_max_attempts: body.max_attempts ?? 3,
  });

  if (error) {
    return new Response(
      JSON.stringify({ error: "rpc_error", message: error.message }),
      {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
});
