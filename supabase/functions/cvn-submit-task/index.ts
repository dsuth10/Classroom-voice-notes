// supabase/functions/cvn-submit-task/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { authenticateClient } from "../_shared/client_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-cvn-signature, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SCHEMA_VERSION = "cvn.agent_task.v1";
const STALE_TIMESTAMP_SECONDS = 300; // 5 min
const MAX_INSTRUCTIONS_LENGTH = 5000;
const MAX_TITLE_LENGTH = 200;

const HMAC_SECRET = Deno.env.get("CVN_HMAC_SECRET") ?? "";
const BEARER_TOKEN = Deno.env.get("CVN_BEARER_TOKEN") ?? "";
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

function validateSchema(p: any): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  if (p?.schema_version !== SCHEMA_VERSION) {
    errors.push("schema_version must be cvn.agent_task.v1");
  }
  if (
    typeof p?.task_id !== "string" ||
    !/^CVN-\d{8}-\d{6}-[A-Z0-9]{4}$/.test(p.task_id)
  ) {
    errors.push("task_id must match CVN-YYYYMMDD-HHMMSS-XXXX");
  }
  if (typeof p?.source !== "string") errors.push("source required");
  if (!["hermes", "openclaw", "auto"].includes(p?.target_agent)) {
    errors.push("target_agent must be hermes/openclaw/auto");
  }
  if (p?.privacy?.classification !== "non_sensitive") {
    errors.push("privacy.classification must be non_sensitive");
  }
  if (
    typeof p?.privacy?.policy_gate_version !== "string" ||
    p.privacy.policy_gate_version.length === 0
  ) {
    errors.push("privacy.policy_gate_version required");
  }
  if (
    !Array.isArray(p?.privacy?.checks_passed) ||
    p.privacy.checks_passed.length === 0
  ) {
    errors.push("privacy.checks_passed required, non-empty array");
  }
  if (
    typeof p?.task?.title !== "string" ||
    p.task.title.length === 0 ||
    p.task.title.length > MAX_TITLE_LENGTH
  ) {
    errors.push(`task.title required, 1-${MAX_TITLE_LENGTH} chars`);
  }
  if (
    typeof p?.task?.instructions !== "string" ||
    p.task.instructions.length === 0 ||
    p.task.instructions.length > MAX_INSTRUCTIONS_LENGTH
  ) {
    errors.push(
      `task.instructions required, 1-${MAX_INSTRUCTIONS_LENGTH} chars`,
    );
  }
  if (
    p?.task?.priority &&
    !["low", "normal", "high", "urgent"].includes(p.task.priority)
  ) {
    errors.push("task.priority must be low/normal/high/urgent");
  }
  if (typeof p?.signed_at !== "string" || isNaN(Date.parse(p.signed_at))) {
    errors.push("signed_at required, valid ISO timestamp");
  }
  if (
    typeof p?.nonce !== "string" ||
    p.nonce.length < 16 ||
    p.nonce.length > 64
  ) {
    errors.push("nonce required, 16-64 chars");
  }
  if (
    typeof p?.idempotency_key !== "string" ||
    p.idempotency_key.length < 8 ||
    p.idempotency_key.length > 128
  ) {
    errors.push("idempotency_key required, 8-128 chars");
  }
  return { valid: errors.length === 0, errors };
}

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
  if (!HMAC_SECRET || !BEARER_TOKEN || !SUPABASE_URL || !SUPABASE_SERVICE_KEY) {
    console.error("Missing required secrets");
    return new Response("Server misconfigured", {
      status: 500,
      headers: corsHeaders,
    });
  }

  const body = await req.text();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  // 1. Strict 5-Element Client Authentication & Atomic DB Nonce Registration
  try {
    await authenticateClient(req, body, supabase);
  } catch (err: any) {
    return new Response(
      JSON.stringify({ error: err.message || "Unauthorized" }),
      {
        status: 401,
        headers: { ...corsHeaders, "content-type": "application/json" },
      },
    );
  }

  // 3. Parse JSON
  let payload: any;
  try {
    payload = JSON.parse(body);
  } catch {
    return new Response("Invalid JSON", { status: 400, headers: corsHeaders });
  }

  // 4. Stale timestamp check
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

  // 5. Schema validation
  const v = validateSchema(payload);
  if (!v.valid) {
    return new Response(
      JSON.stringify({ error: "schema_validation_failed", errors: v.errors }),
      {
        status: 400,
        headers: { ...corsHeaders, "content-type": "application/json" },
      },
    );
  }

  // 6. DB Client initialization and execution
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  // Check nonce replay protection for client requests
  // Insert into cvn_processed_nonces (nonces table has UNIQUE constraint on nonce)
  const payloadHash = await sha256Hex(body);
  const { error: nonceError } = await supabase
    .from("cvn_processed_nonces")
    .insert({
      nonce: payload.nonce,
      worker_id: payload.source_device_id ?? "unknown",
      endpoint: "cvn-submit-task",
      signed_at: payload.signed_at,
      request_hash: payloadHash,
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

  // Call stored procedure cvn_submit_task
  const { data, error } = await supabase.rpc("cvn_submit_task", {
    p_task_id: payload.task_id,
    p_source_device_id: payload.source_device_id ?? "unknown",
    p_target_agent: payload.target_agent,
    p_priority: payload.task.priority ?? "normal",
    p_payload_json: payload,
    p_payload_hash: payloadHash,
    p_privacy_classification: payload.privacy.classification,
    p_policy_gate_version: payload.privacy.policy_gate_version,
    p_checks_passed: payload.privacy.checks_passed,
    p_redactions_applied: payload.redactions_applied ?? [],
    p_idempotency_key: payload.idempotency_key,
    p_nonce: payload.nonce,
    p_signed_at: payload.signed_at,
  });

  if (error) {
    if (
      error.code === "23505" ||
      /duplicate_idempotency_key/i.test(error.message ?? "")
    ) {
      const { data: existing } = await supabase
        .from("cvn_tasks")
        .select("task_id")
        .eq("idempotency_key", payload.idempotency_key)
        .maybeSingle();
      return new Response(
        JSON.stringify({
          error: "duplicate_idempotency_key",
          task_id: existing?.task_id ?? payload.task_id,
        }),
        {
          status: 409,
          headers: { ...corsHeaders, "content-type": "application/json" },
        },
      );
    }
    console.error("cvn_submit_task RPC error:", error);
    return new Response(JSON.stringify({ error: "internal_error" }), {
      status: 500,
      headers: { ...corsHeaders, "content-type": "application/json" },
    });
  }

  const row = Array.isArray(data) ? data[0] : data;
  return new Response(
    JSON.stringify({
      accepted: true,
      task_id: row?.task_id ?? payload.task_id,
      status_url:
        row?.status_url ?? `/functions/v1/cvn-status/${payload.task_id}`,
      msg_id: row?.msg_id,
    }),
    {
      status: 200,
      headers: { ...corsHeaders, "content-type": "application/json" },
    },
  );
});
