// supabase/functions/cvn-outbound-status/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import {
  authenticateClient,
  ClientAuthenticationError,
} from "../_shared/client_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-cvn-signature, x-cvn-client-key-id, x-cvn-key-id, x-cvn-timestamp, x-cvn-nonce, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

function safeReasonCode(value: unknown): string {
  const firstToken = String(value ?? "").trim().split(/\s+/, 1)[0]
    .replace(/:$/, "");
  return /^[A-Z][A-Z0-9_:-]{1,95}$/.test(firstToken)
    ? firstToken
    : "ACTION_BLOCKED";
}

function safeResultReference(value: unknown): string | null {
  const candidate = String(value ?? "").trim();
  return /^[a-z][a-z0-9_]{1,47}:[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$/
      .test(candidate) && candidate.length <= 256
    ? candidate
    : null;
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

  let text = "";
  try {
    text = await req.text();
  } catch (_e) {
    text = "";
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  let clientIdentity;
  try {
    clientIdentity = await authenticateClient(req, text, supabase);
  } catch (err: any) {
    return new Response(
      JSON.stringify({
        error: "unauthorized",
        message: err instanceof ClientAuthenticationError
          ? err.message
          : "Client authentication failed",
      }),
      {
        status: 401,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }

  let itemId = "";
  let requestedSourceDeviceId = "";
  try {
    if (text) {
      const body = JSON.parse(text);
      itemId = body.item_id ?? "";
      requestedSourceDeviceId = body.source_device_id ?? "";
    }
  } catch (_e) {
    return new Response(JSON.stringify({ error: "invalid_json" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  if (!itemId) {
    return new Response(JSON.stringify({ error: "item_id_required" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const authorisedSourceDeviceId = clientIdentity.source_device_id ||
    requestedSourceDeviceId;
  if (!authorisedSourceDeviceId) {
    return new Response(JSON.stringify({ error: "source_device_id_required" }), {
      status: 403,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
  if (
    clientIdentity.source_device_id && requestedSourceDeviceId &&
    requestedSourceDeviceId !== clientIdentity.source_device_id
  ) {
    return new Response(JSON.stringify({ error: "device_mismatch" }), {
      status: 403,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const { data, error } = await supabase.rpc("cvn_get_outbound_item_status", {
    p_item_id: itemId,
    p_source_device_id: authorisedSourceDeviceId,
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

  const row = typeof data === "object" && data !== null
    ? data as Record<string, unknown>
    : {};
  // Lifecycle-only allowlist: RPC additions can never become desktop telemetry
  // unless they are deliberately reviewed and added here.
  const safeData = {
    found: row.found === true,
    item_id: typeof row.item_id === "string" ? row.item_id : itemId,
    status: typeof row.status === "string" ? row.status : null,
    created_at: typeof row.created_at === "string" ? row.created_at : null,
    claimed_at: typeof row.claimed_at === "string" ? row.claimed_at : null,
    completed_at: typeof row.completed_at === "string" ? row.completed_at : null,
    failed_at: typeof row.failed_at === "string" ? row.failed_at : null,
    result_reference: safeResultReference(row.result_reference),
    blocked_reason: row.failure_reason == null
      ? null
      : safeReasonCode(row.failure_reason),
  };

  return new Response(JSON.stringify(safeData), {
    status: 200,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
});
