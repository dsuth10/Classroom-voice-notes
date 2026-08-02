// supabase/functions/cvn-outbound-status/index.ts
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import {
  authenticateWorker,
  AuthenticationError,
} from "../_shared/broker_auth.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-cvn-signature, x-cvn-key-id, x-cvn-timestamp, x-cvn-nonce, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

serve(async (req: Request) => {
  if (req.method === "OPTIONS")
    return new Response("ok", { headers: corsHeaders });

  let text = "";
  try {
    text = await req.text();
  } catch (_e) {
    text = "";
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  try {
    await authenticateWorker(req, text, supabase);
  } catch (err) {
    if (err instanceof AuthenticationError) {
      return new Response(
        JSON.stringify({ error: "unauthorized", message: err.message }),
        {
          status: 401,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      );
    }
  }

  let itemId = "";
  if (req.method === "GET") {
    const url = new URL(req.url);
    itemId = url.searchParams.get("item_id") ?? "";
  } else if (req.method === "POST") {
    try {
      const text = await req.text();
      if (text) {
        const body = JSON.parse(text);
        itemId = body.item_id ?? "";
      }
    } catch (_e) {
      return new Response(JSON.stringify({ error: "invalid_json" }), {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }
  }

  if (!itemId) {
    return new Response(JSON.stringify({ error: "item_id_required" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
  const { data, error } = await supabase.rpc("cvn_get_outbound_item_status", {
    p_item_id: itemId,
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
