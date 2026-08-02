// supabase/functions/cvn-fail-task/index.ts
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
const MAX_ERROR_MESSAGE_LENGTH = 1000;

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

  // Validate parameters
  if (typeof payload?.task_id !== "string" || payload.task_id.length === 0) {
    return new Response(JSON.stringify({ error: "missing_task_id" }), {
      status: 400,
      headers: { ...corsHeaders, "content-type": "application/json" },
    });
  }
  const workerId = payload?.worker_id ?? payload?.claim_token;
  if (typeof workerId !== "string" || workerId.length === 0) {
    return new Response("worker_id or claim_token required", {
      status: 400,
      headers: corsHeaders,
    });
  }

  let errorMsg: string;
  let errorCode: string;
  let disposition: string;

  if (payload?.failure && typeof payload.failure === "object") {
    errorMsg = payload.failure.message;
    errorCode = payload.failure.code;
    disposition = payload.failure.disposition;
  } else {
    errorMsg = payload?.error_message;
    errorCode = "LEGACY_ERROR";
    disposition = "retryable";
  }

  if (
    typeof errorMsg !== "string" ||
    errorMsg.length === 0 ||
    errorMsg.length > MAX_ERROR_MESSAGE_LENGTH
  ) {
    return new Response(
      `error message required, max ${MAX_ERROR_MESSAGE_LENGTH} chars`,
      {
        status: 400,
        headers: corsHeaders,
      },
    );
  }
  if (typeof errorCode !== "string" || errorCode.length === 0) {
    return new Response("error code required", {
      status: 400,
      headers: corsHeaders,
    });
  }
  if (!["retryable", "permanent", "execution_unknown"].includes(disposition)) {
    return new Response("Invalid failure disposition", {
      status: 400,
      headers: corsHeaders,
    });
  }

  // Authorize worker ID constraint if not legacy
  if (!principal.legacy) {
    if (
      !principal.allowed_worker_ids ||
      !principal.allowed_worker_ids.includes(workerId)
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
      worker_id: workerId,
      endpoint: "cvn-fail-task",
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

  // Atomic DB Fail with allowed_targets
  const { data, error } = await supabase.rpc("cvn_fail_task", {
    p_task_id: payload.task_id,
    p_worker_id: workerId,
    p_error_message: errorMsg,
    p_error_code: errorCode,
    p_disposition: disposition,
    p_max_retries: 5,
    p_allowed_targets: principal.allowed_targets,
  });

  if (error) {
    console.error("cvn_fail_task RPC error:", error);
    return new Response(JSON.stringify({ error: "internal_error" }), {
      status: 500,
      headers: { ...corsHeaders, "content-type": "application/json" },
    });
  }

  const result = Array.isArray(data) ? data[0] : data;
  if (!result || !result.success) {
    const errCode = result?.message ?? "unknown_error";
    if (errCode === "task_claimed_by_another_worker") {
      return new Response(JSON.stringify({ error: errCode }), {
        status: 409,
        headers: { ...corsHeaders, "content-type": "application/json" },
      });
    } else if (errCode === "unauthorized_target" || !result.status) {
      return new Response(JSON.stringify({ error: "unauthorized" }), {
        status: 403,
        headers: { ...corsHeaders, "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ error: errCode }), {
      status: 400,
      headers: { ...corsHeaders, "content-type": "application/json" },
    });
  }

  return new Response(
    JSON.stringify({
      success: true,
      status: result.status,
      retry_count: result.retry_count,
    }),
    {
      status: 200,
      headers: { ...corsHeaders, "content-type": "application/json" },
    },
  );
});
