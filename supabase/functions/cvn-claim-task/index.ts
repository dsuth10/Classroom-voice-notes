// supabase/functions/cvn-claim-task/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import {
  authenticateWorker,
  AuthenticationError,
  sha256Hex,
} from "../_shared/broker_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-cvn-signature, x-cvn-key-id, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const STALE_TIMESTAMP_SECONDS = 300; // 5 min
const MAX_BODY_SIZE_BYTES = 20 * 1024; // 20KB

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", {
      status: 405,
      headers: corsHeaders,
    });
  }

  const contentType = req.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return new Response("Unsupported Media Type", {
      status: 415,
      headers: corsHeaders,
    });
  }

  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) {
    console.error("Missing required Supabase secrets");
    return new Response("Server misconfigured", {
      status: 500,
      headers: corsHeaders,
    });
  }

  // Enforce size limit and read exact body once
  let body: string;
  try {
    const buf = await req.arrayBuffer();
    if (buf.byteLength > MAX_BODY_SIZE_BYTES) {
      return new Response("Payload Too Large", {
        status: 413,
        headers: corsHeaders,
      });
    }
    body = new TextDecoder().decode(buf);
  } catch (e) {
    return new Response("Error reading body", {
      status: 400,
      headers: corsHeaders,
    });
  }

  // Authenticate before parsing business fields
  let principal;
  try {
    principal = await authenticateWorker(req, body);
  } catch (e) {
    if (e instanceof AuthenticationError) {
      return new Response(e.message, { status: 401, headers: corsHeaders });
    }
    console.error("Authentication check error:", e);
    return new Response("Internal Server Error", {
      status: 500,
      headers: corsHeaders,
    });
  }

  // Parse JSON
  let payload: any;
  try {
    payload = JSON.parse(body);
  } catch {
    return new Response("Invalid JSON", { status: 400, headers: corsHeaders });
  }

  // Validate basic parameters
  if (
    typeof payload?.worker_id !== "string" ||
    payload.worker_id.length === 0
  ) {
    return new Response("worker_id required", {
      status: 400,
      headers: corsHeaders,
    });
  }
  const vtSeconds =
    typeof payload?.vt_seconds === "number" ? payload.vt_seconds : 1800; // 30 mins default
  const targetAgent = payload?.target_agent ?? "hermes";
  if (!["hermes", "openclaw"].includes(targetAgent)) {
    return new Response("Invalid target_agent", {
      status: 400,
      headers: corsHeaders,
    });
  }

  // Authorize
  if (!principal.allowed_targets.includes(targetAgent)) {
    return new Response(JSON.stringify({ error: "unauthorized_target" }), {
      status: 403,
      headers: { ...corsHeaders, "content-type": "application/json" },
    });
  }

  if (!principal.legacy) {
    if (
      !principal.allowed_worker_ids ||
      !principal.allowed_worker_ids.includes(payload.worker_id)
    ) {
      return new Response(JSON.stringify({ error: "unauthorized_worker_id" }), {
        status: 403,
        headers: { ...corsHeaders, "content-type": "application/json" },
      });
    }
  }

  // Stale timestamp check
  const signedAtMs = Date.parse(payload.signed_at);
  if (isNaN(signedAtMs)) {
    return new Response("Invalid signed_at", {
      status: 400,
      headers: corsHeaders,
    });
  }
  const ageSec = (Date.now() - signedAtMs) / 1000;
  if (Math.abs(ageSec) > STALE_TIMESTAMP_SECONDS) {
    return new Response("Stale signed_at", {
      status: 401,
      headers: corsHeaders,
    });
  }

  // Nonce replay protection
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const requestHash = await sha256Hex(body);
  const { error: nonceError } = await supabase
    .from("cvn_processed_nonces")
    .insert({
      nonce: payload.nonce,
      worker_id: payload.worker_id,
      endpoint: "cvn-claim-task",
      signed_at: payload.signed_at,
      request_hash: requestHash,
    });

  if (nonceError) {
    if (nonceError.code === "23505") {
      return new Response(JSON.stringify({ error: "duplicate_nonce" }), {
        status: 401,
        headers: { ...corsHeaders, "content-type": "application/json" },
      });
    }
    console.error("Nonce tracking error:", nonceError);
  }

  // Atomic DB Claim
  const { data, error } = await supabase.rpc("cvn_claim_next_task", {
    p_worker_id: payload.worker_id,
    p_vt_seconds: vtSeconds,
    p_target_agent: targetAgent,
  });

  if (error) {
    console.error("cvn_claim_next_task RPC error:", error);
    return new Response(JSON.stringify({ error: "internal_error" }), {
      status: 500,
      headers: { ...corsHeaders, "content-type": "application/json" },
    });
  }

  const result = Array.isArray(data) ? data[0] : data;
  if (!result || !result.claimed) {
    return new Response(
      JSON.stringify({ claimed: false, reason: "no_pending_tasks" }),
      {
        status: 200,
        headers: { ...corsHeaders, "content-type": "application/json" },
      },
    );
  }

  return new Response(
    JSON.stringify({
      claimed: true,
      task_id: result.task_id,
      target_agent: result.target_agent,
      status: result.status,
      payload: result.payload_json,
    }),
    {
      status: 200,
      headers: { ...corsHeaders, "content-type": "application/json" },
    },
  );
});
