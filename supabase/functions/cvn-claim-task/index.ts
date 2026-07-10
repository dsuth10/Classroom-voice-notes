// supabase/functions/cvn-claim-task/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-cvn-signature, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const STALE_TIMESTAMP_SECONDS = 300; // 5 min

const AGENT_BROKER_HMAC_SECRET = Deno.env.get("AGENT_BROKER_HMAC_SECRET") ?? "";
const AGENT_BROKER_BEARER_TOKEN = Deno.env.get("AGENT_BROKER_BEARER_TOKEN") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

async function hmacSha256Hex(body: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(s),
  );
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405, headers: corsHeaders });
  }
  if (!AGENT_BROKER_HMAC_SECRET || !AGENT_BROKER_BEARER_TOKEN || !SUPABASE_URL || !SUPABASE_SERVICE_KEY) {
    console.error("Missing required secrets");
    return new Response("Server misconfigured", { status: 500, headers: corsHeaders });
  }

  // 1. Bearer Token Auth
  const auth = req.headers.get("authorization") ?? "";
  if (!auth.startsWith("Bearer ") || !timingSafeEqual(auth.slice(7), AGENT_BROKER_BEARER_TOKEN)) {
    return new Response("Unauthorized", { status: 401, headers: corsHeaders });
  }

  const body = await req.text();

  // 2. HMAC verify
  const signature = req.headers.get("x-cvn-signature") ?? "";
  const expected = await hmacSha256Hex(body, AGENT_BROKER_HMAC_SECRET);
  if (!signature || !timingSafeEqual(signature.toLowerCase(), expected)) {
    return new Response("Invalid signature", { status: 401, headers: corsHeaders });
  }

  // 3. Parse JSON
  let payload: any;
  try {
    payload = JSON.parse(body);
  } catch {
    return new Response("Invalid JSON", { status: 400, headers: corsHeaders });
  }

  // 4. Validate parameters
  if (typeof payload?.worker_id !== "string" || payload.worker_id.length === 0) {
    return new Response("worker_id required", { status: 400, headers: corsHeaders });
  }
  const vtSeconds = typeof payload?.vt_seconds === "number" ? payload.vt_seconds : 1800; // 30 mins default
  const targetAgent = payload?.target_agent ?? "hermes";
  if (!["hermes", "openclaw"].includes(targetAgent)) {
    return new Response("Invalid target_agent", { status: 400, headers: corsHeaders });
  }

  // 5. Stale timestamp check
  const signedAtMs = Date.parse(payload.signed_at);
  if (isNaN(signedAtMs)) {
    return new Response("Invalid signed_at", { status: 400, headers: corsHeaders });
  }
  const ageSec = (Date.now() - signedAtMs) / 1000;
  if (Math.abs(ageSec) > STALE_TIMESTAMP_SECONDS) {
    return new Response("Stale signed_at", { status: 401, headers: corsHeaders });
  }

  // 6. Nonce replay protection
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const requestHash = await sha256Hex(body);
  const { error: nonceError } = await supabase
    .from("cvn_processed_nonces")
    .insert({
      nonce: payload.nonce,
      worker_id: payload.worker_id,
      endpoint: "cvn-claim-task",
      signed_at: payload.signed_at,
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

  // 7. Atomic DB Claim
  const { data, error } = await supabase.rpc("cvn_claim_next_task", {
    p_worker_id: payload.worker_id,
    p_vt_seconds: vtSeconds,
    p_target_agent: targetAgent
  });

  if (error) {
    console.error("cvn_claim_next_task RPC error:", error);
    return new Response(JSON.stringify({ error: "internal_error" }), {
      status: 500,
      headers: { ...corsHeaders, "content-type": "application/json" }
    });
  }

  const result = Array.isArray(data) ? data[0] : data;
  if (!result || !result.claimed) {
    return new Response(
      JSON.stringify({ claimed: false, reason: "no_pending_tasks" }),
      { status: 200, headers: { ...corsHeaders, "content-type": "application/json" } }
    );
  }

  return new Response(
    JSON.stringify({
      claimed: true,
      task_id: result.task_id,
      target_agent: result.target_agent,
      status: result.status,
      payload: result.payload_json
    }),
    { status: 200, headers: { ...corsHeaders, "content-type": "application/json" } }
  );
});
