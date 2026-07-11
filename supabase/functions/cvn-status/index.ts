// supabase/functions/cvn-status/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { authenticateWorker, AuthenticationError, sha256Hex, hmacSha256Hex, timingSafeEqual } from "../_shared/broker_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-cvn-signature, x-cvn-key-id, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

const STALE_TIMESTAMP_SECONDS = 300; // 5 min

const CVN_HMAC_SECRET = Deno.env.get("CVN_HMAC_SECRET") ?? "";
const CVN_BEARER_TOKEN = Deno.env.get("CVN_BEARER_TOKEN") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  if (req.method !== "GET") {
    return new Response("Method not allowed", { status: 405, headers: corsHeaders });
  }
  if (!CVN_HMAC_SECRET || !CVN_BEARER_TOKEN || !SUPABASE_URL || !SUPABASE_SERVICE_KEY) {
    console.error("Missing required secrets");
    return new Response("Server misconfigured", { status: 500, headers: corsHeaders });
  }

  // 1. Parse URL & Path
  const url = new URL(req.url);
  const pathParts = url.pathname.split("/").filter(Boolean);
  const taskId = pathParts[1] ?? "";
  
  if (!taskId || !/^CVN-\d{8}-\d{6}-[A-Z0-9]{4}$/.test(taskId)) {
    return new Response(JSON.stringify({ error: "missing_task_id" }), {
      status: 400,
      headers: { ...corsHeaders, "content-type": "application/json" }
    });
  }

  // 2. Parse Query Params
  const signedAt = url.searchParams.get("signed_at") ?? "";
  const nonce = url.searchParams.get("nonce") ?? "";

  if (!signedAt || !nonce || nonce.length < 16 || nonce.length > 64) {
    return new Response("Missing or invalid signed_at/nonce", { status: 400, headers: corsHeaders });
  }

  // 3. Stale timestamp check
  const signedAtMs = Date.parse(signedAt);
  if (isNaN(signedAtMs)) {
    return new Response("Invalid signed_at", { status: 400, headers: corsHeaders });
  }
  const ageSec = (Date.now() - signedAtMs) / 1000;
  if (Math.abs(ageSec) > STALE_TIMESTAMP_SECONDS) {
    return new Response("Stale signed_at", { status: 401, headers: corsHeaders });
  }

  const canonicalString = `GET\n/functions/v1/cvn-status/${taskId}\ntask_id=${taskId}\nsigned_at=${signedAt}\nnonce=${nonce}`;

  // 4. Authenticate Client vs Worker
  const authHeader = req.headers.get("authorization") ?? "";
  const keyId = req.headers.get("x-cvn-key-id") ?? "";
  let principal = null;
  let isClient = false;

  // If there's no key-id, we must check if it's the client.
  if (!keyId && authHeader.startsWith("Bearer ")) {
    const providedBearer = authHeader.slice(7);
    const providedBearerHash = await sha256Hex(providedBearer);
    const clientBearerHash = await sha256Hex(CVN_BEARER_TOKEN);
    
    if (timingSafeEqual(providedBearerHash, clientBearerHash)) {
      isClient = true;
      const signature = req.headers.get("x-cvn-signature") ?? "";
      const expected = await hmacSha256Hex(canonicalString, CVN_HMAC_SECRET);
      if (!signature || !timingSafeEqual(signature.toLowerCase(), expected.toLowerCase())) {
        return new Response("Invalid signature", { status: 401, headers: corsHeaders });
      }
    }
  }

  if (!isClient) {
    // Attempt worker authentication (will fall back to legacy if no keyId)
    try {
      principal = await authenticateWorker(req, canonicalString);
    } catch (e) {
      if (e instanceof AuthenticationError) {
        return new Response(e.message, { status: 401, headers: corsHeaders });
      }
      console.error("Authentication check error:", e);
      return new Response("Internal Server Error", { status: 500, headers: corsHeaders });
    }
  }

  // 5. Nonce replay protection
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const requestHash = await sha256Hex(canonicalString);
  const { error: nonceError } = await supabase
    .from("cvn_processed_nonces")
    .insert({
      nonce: nonce,
      worker_id: isClient ? "client" : principal?.key_id,
      endpoint: "cvn-status",
      signed_at: signedAt,
      request_hash: requestHash
    });

  if (nonceError) {
    if (nonceError.code === "23505") {
      return new Response(JSON.stringify({ error: "duplicate_nonce" }), {
        status: 401,
        headers: { ...corsHeaders, "content-type": "application/json" }
      });
    }
    console.error("Nonce tracking error:", nonceError);
  }

  // 6. Query Task (withhold sensitive payload)
  const { data: task, error } = await supabase
    .from("cvn_tasks")
    .select("task_id, status, target_agent, created_at, claimed_at, completed_at, failed_at, retry_count, result_summary, error_message, error_code")
    .eq("task_id", taskId)
    .maybeSingle();

  if (error) {
    console.error("Database query error:", error);
    return new Response(JSON.stringify({ error: "internal_error" }), {
      status: 500,
      headers: { ...corsHeaders, "content-type": "application/json" }
    });
  }

  if (!task) {
    return new Response(JSON.stringify({ error: "task_not_found" }), {
      status: 404,
      headers: { ...corsHeaders, "content-type": "application/json" }
    });
  }

  // 7. Authorize worker
  if (!isClient && principal) {
    if (!principal.allowed_targets.includes(task.target_agent)) {
      return new Response(JSON.stringify({ error: "unauthorized_target" }), {
        status: 403,
        headers: { ...corsHeaders, "content-type": "application/json" }
      });
    }
  }

  return new Response(JSON.stringify(task), {
    status: 200,
    headers: { ...corsHeaders, "content-type": "application/json" }
  });
});
