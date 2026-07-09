// supabase/functions/cvn-status/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-cvn-signature, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

const STALE_TIMESTAMP_SECONDS = 300; // 5 min

const CVN_HMAC_SECRET = Deno.env.get("CVN_HMAC_SECRET") ?? "";
const CVN_BEARER_TOKEN = Deno.env.get("CVN_BEARER_TOKEN") ?? "";
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
  if (req.method !== "GET") {
    return new Response("Method not allowed", { status: 405, headers: corsHeaders });
  }
  if (
    !CVN_HMAC_SECRET || !CVN_BEARER_TOKEN || 
    !AGENT_BROKER_HMAC_SECRET || !AGENT_BROKER_BEARER_TOKEN || 
    !SUPABASE_URL || !SUPABASE_SERVICE_KEY
  ) {
    console.error("Missing required secrets");
    return new Response("Server misconfigured", { status: 500, headers: corsHeaders });
  }

  // 1. Parse URL & Path
  const url = new URL(req.url);
  const pathParts = url.pathname.split("/").filter(Boolean);
  // Expected path format: /functions/v1/cvn-status/<task_id>
  // pathParts will be ["cvn-status", "<task_id>"]
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

  // 4. Authenticate Bearer
  const auth = req.headers.get("authorization") ?? "";
  let matchedRole: "client" | "worker" | null = null;
  
  if (auth.startsWith("Bearer ")) {
    const token = auth.slice(7);
    if (timingSafeEqual(token, CVN_BEARER_TOKEN)) {
      matchedRole = "client";
    } else if (timingSafeEqual(token, AGENT_BROKER_BEARER_TOKEN)) {
      matchedRole = "worker";
    }
  }

  if (!matchedRole) {
    return new Response("Unauthorized", { status: 401, headers: corsHeaders });
  }

  // 5. Verify Signature over Canonical String
  // Canonical string: GET\n/functions/v1/cvn-status/<task_id>\ntask_id=<task_id>\nsigned_at=<signed_at>\nnonce=<nonce>
  const canonicalString = `GET\n/functions/v1/cvn-status/${taskId}\ntask_id=${taskId}\nsigned_at=${signedAt}\nnonce=${nonce}`;
  const signature = req.headers.get("x-cvn-signature") ?? "";
  
  const secret = matchedRole === "client" ? CVN_HMAC_SECRET : AGENT_BROKER_HMAC_SECRET;
  const expected = await hmacSha256Hex(canonicalString, secret);

  if (!signature || !timingSafeEqual(signature.toLowerCase(), expected)) {
    return new Response("Invalid signature", { status: 401, headers: corsHeaders });
  }

  // 6. Nonce replay protection
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const requestHash = await sha256Hex(canonicalString);
  const { error: nonceError } = await supabase
    .from("cvn_processed_nonces")
    .insert({
      nonce: nonce,
      worker_id: matchedRole,
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

  // 7. Query Task (withhold sensitive payload)
  const { data: task, error } = await supabase
    .from("cvn_tasks")
    .select("task_id, status, target_agent, created_at, claimed_at, completed_at, failed_at, retry_count, result_summary, error_message")
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

  return new Response(JSON.stringify(task), {
    status: 200,
    headers: { ...corsHeaders, "content-type": "application/json" }
  });
});
