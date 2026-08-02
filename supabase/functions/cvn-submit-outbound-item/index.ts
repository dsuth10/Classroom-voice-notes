// supabase/functions/cvn-submit-outbound-item/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { computeCanonicalHash, isValidHexSha256 } from "../_shared/outbound_contract.ts";
import { authenticateClient, ClientAuthenticationError } from "../_shared/client_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-cvn-signature, x-cvn-client-key-id, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SCHEMA_VERSION = "cvn.outbound_item.v2";
const STALE_TIMESTAMP_SECONDS = 300; // 5 min
const MAX_BODY_SIZE_BYTES = 512 * 1024; // 512 KB

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

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
  if (!["openclaw"].includes(p?.target_agent)) {
    errors.push("target_agent must be openclaw");
  }
  if (
    typeof p?.idempotency_key !== "string" ||
    p.idempotency_key.trim().length < 8
  ) {
    errors.push("idempotency_key must be a non-empty string");
  }
  if (typeof p?.nonce !== "string" || p.nonce.trim().length < 8) {
    errors.push("nonce must be a non-empty string");
  }
  if (!isValidHexSha256(p?.content_hash)) {
    errors.push("content_hash must be a valid lowercase 64-char SHA-256 string");
  }

  const releaseBasis = p?.privacy?.release_basis;
  if (
    !["automatic_policy", "human_approval", "trusted_mode"].includes(
      releaseBasis,
    )
  ) {
    errors.push("privacy.release_basis required");
  }

  if (["human_approval", "trusted_mode"].includes(releaseBasis)) {
    const app = p?.privacy?.approval;
    if (!app || typeof app !== "object") {
      errors.push("privacy.approval block required for human_approval/trusted_mode");
    } else {
      if (!app.approved_at) {
        errors.push("privacy.approval.approved_at required");
      }
      if (!isValidHexSha256(app.approved_content_hash)) {
        errors.push("privacy.approval.approved_content_hash must be a valid lowercase 64-char hex SHA-256 string");
      } else if (app.approved_content_hash !== p?.content_hash) {
        errors.push("privacy.approval.approved_content_hash must match content_hash");
      }
    }
  }

  if (releaseBasis === "automatic_policy") {
    const checks = p?.privacy?.checks_passed;
    if (!Array.isArray(checks) || checks.length === 0) {
      errors.push("privacy.checks_passed array required for automatic_policy");
    }
  }

  if (p?.item_kind === "record_only" && p?.task != null && Object.keys(p.task).length > 0) {
    errors.push("record_only items must have task empty or null");
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

  // 1. Read body & check max size limit
  const bodyText = await req.text();
  const bodyBytes = new TextEncoder().encode(bodyText).length;
  if (bodyBytes > MAX_BODY_SIZE_BYTES) {
    return new Response(JSON.stringify({ error: "body_too_large" }), {
      status: 413,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  // 2. Server-Side Client Identity Authentication & Key Derivation
  let clientIdentity;
  try {
    clientIdentity = await authenticateClient(req, bodyText);
  } catch (authErr) {
    return new Response(
      JSON.stringify({
        error: "unauthorized",
        message: authErr instanceof ClientAuthenticationError ? authErr.message : "Client authentication failed",
      }),
      {
        status: 401,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
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

  // 3.5 Device identity binding verification
  if (clientIdentity.source_device_id && clientIdentity.source_device_id !== payload.source_device_id) {
    return new Response(
      JSON.stringify({
        error: "device_identity_mismatch",
        message: "Payload source_device_id does not match authenticated credential device identity",
      }),
      {
        status: 403,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  // 4. Recompute canonical content hash server-side and verify match
  const serverCanonicalHash = await computeCanonicalHash(
    payload.item_kind,
    payload.target_agent,
    payload.content,
    payload.task
  );

  if (serverCanonicalHash !== payload.content_hash) {
    return new Response(
      JSON.stringify({
        error: "content_hash_mismatch",
        message: "Server-derived canonical content hash does not match payload content_hash",
      }),
      {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  if (["human_approval", "trusted_mode"].includes(payload.privacy?.release_basis)) {
    const approvedHash = payload.privacy?.approval?.approved_content_hash;
    if (approvedHash !== serverCanonicalHash) {
      return new Response(
        JSON.stringify({
          error: "approved_content_hash_mismatch",
          message: "Server-derived canonical content hash does not match approved_content_hash",
        }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }
  }

  // 5. Stale timestamp check
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

  // 6. Initialize Supabase Service Role Client
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  // 7. Server-Authorized Trusted Mode Capability Evaluation
  if (payload.privacy?.release_basis === "trusted_mode") {
    const checks = payload.privacy?.checks_passed;
    if (!Array.isArray(checks) || checks.length === 0) {
      return new Response(
        JSON.stringify({
          error: "invalid_trusted_mode_checks",
          message: "privacy.checks_passed array required for trusted_mode",
        }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }

    // DERIVE client_key_id FROM AUTHENTICATED SERVER IDENTITY — ignore/override caller spoofing
    const serverClientKeyId = clientIdentity.key_id;
    const environment = clientIdentity.environment;
    const policyVersion = payload.privacy?.policy_gate_version ?? "2.0.0";

    const { data: entResult, error: entErr } = await supabase.rpc(
      "cvn_evaluate_trusted_entitlement",
      {
        p_client_key_id: serverClientKeyId,
        p_source_device_id: payload.source_device_id,
        p_environment: environment,
        p_item_kind: payload.item_kind,
        p_target_agent: payload.target_agent,
        p_risk_level: payload.privacy?.risk_level ?? "low",
        p_policy_version: policyVersion,
      },
    );

    if (entErr || !entResult || !entResult.allowed) {
      return new Response(
        JSON.stringify({
          error: "trusted_mode_unauthorized",
          reason_code: entResult?.reason_code ?? "entitlement_check_failed",
          message: entResult?.error_message ?? "Trusted mode entitlement check failed",
        }),
        {
          status: 403,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }
  }

  // 8. Invoke Supabase Submission RPC
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
