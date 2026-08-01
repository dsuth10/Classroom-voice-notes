// supabase/functions/cvn-submit-outbound-item/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-cvn-signature, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SCHEMA_VERSION = "cvn.outbound_item.v2";
const STALE_TIMESTAMP_SECONDS = 300; // 5 min

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
    errors.push(`schema_version must be ${SCHEMA_VERSION}`);
  }
  if (
    typeof p?.item_id !== "string" ||
    !/^CVNI-\d{8}-\d{6}-[A-Z0-9]{4}$/.test(p.item_id)
  ) {
    errors.push("item_id must match CVNI-YYYYMMDD-HHMMSS-XXXX");
  }
  if (!["record_only", "agent_task"].includes(p?.item_kind)) {
    errors.push("item_kind must be record_only or agent_task");
  }
  if (!["hermes", "openclaw", "auto"].includes(p?.target_agent)) {
    errors.push("target_agent must be hermes/openclaw/auto");
  }
  if (
    !["automatic_policy", "human_approval", "trusted_mode"].includes(
      p?.privacy?.release_basis,
    )
  ) {
    errors.push("privacy.release_basis required");
  }
  if (p?.item_kind === "record_only" && p?.task != null) {
    errors.push("record_only items must have task null");
  }
  if (
    p?.item_kind === "agent_task" &&
    (!p?.task?.title || !p?.task?.instructions)
  ) {
    errors.push("agent_task items require task title and instructions");
  }
  return { valid: errors.length === 0, errors };
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method_not_allowed" }), {
      status: 405,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // 1. Auth header check
  const authHeader = req.headers.get("authorization") ?? "";
  const expectedAuth = `Bearer ${BEARER_TOKEN}`;
  if (!BEARER_TOKEN || !timingSafeEqual(authHeader, expectedAuth)) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // 2. Read body & HMAC check
  const bodyText = await req.text();
  const signatureHeader = req.headers.get("x-cvn-signature") ?? "";
  const computedSignature = await hmacSha256Hex(bodyText, HMAC_SECRET);

  if (!HMAC_SECRET || !timingSafeEqual(signatureHeader, computedSignature)) {
    return new Response(JSON.stringify({ error: "invalid_signature" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // 3. Parse JSON & Validate Schema
  let payload: any;
  try {
    payload = JSON.parse(bodyText);
  } catch (_e) {
    return new Response(JSON.stringify({ error: "invalid_json" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const { valid, errors } = validateSchema(payload);
  if (!valid) {
    return new Response(
      JSON.stringify({ error: "schema_validation_failed", details: errors }),
      {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  // 4. Stale timestamp check
  const signedAtMs = Date.parse(payload.signed_at);
  const nowMs = Date.now();
  if (
    isNaN(signedAtMs) ||
    Math.abs(nowMs - signedAtMs) > STALE_TIMESTAMP_SECONDS * 1000
  ) {
    return new Response(JSON.stringify({ error: "timestamp_stale" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // 5. Invoke Supabase RPC
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const payloadHash = await sha256Hex(bodyText);

  const { data, error } = await supabase.rpc("cvn_submit_outbound_item", {
    p_item_id: payload.item_id,
    p_source_device_id: payload.source_device_id,
    p_item_kind: payload.item_kind,
    p_target_agent: payload.target_agent,
    p_payload_json: payload,
    p_payload_hash: payloadHash,
    p_content_hash: payload.content_hash,
    p_automatic_classification:
      payload.privacy?.automatic_classification ?? "non_sensitive",
    p_risk_level: payload.privacy?.risk_level ?? "low",
    p_release_basis: payload.privacy?.release_basis,
    p_approved_at: payload.privacy?.approval?.approved_at ?? null,
    p_policy_gate_version: payload.privacy?.policy_gate_version ?? "2.0.0",
    p_idempotency_key: payload.idempotency_key,
    p_nonce: payload.nonce,
    p_signed_at: payload.signed_at,
  });

  if (error) {
    if (error.code === "23505") {
      return new Response(
        JSON.stringify({
          error: "duplicate_idempotency_key",
          message: error.message,
        }),
        {
          status: 409,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }
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
