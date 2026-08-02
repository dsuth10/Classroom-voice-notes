// supabase/functions/_shared/client_auth.ts

export type AuthenticatedClient = {
  key_id: string;
  source_device_id?: string;
  environment: string;
};

export class ClientAuthenticationError extends Error {
  constructor(message: string = "Unauthorized") {
    super(message);
    this.name = "ClientAuthenticationError";
  }
}

export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export async function hmacSha256Hex(body: string, secret: string): Promise<string> {
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

export async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Authenticates an incoming client request and derives its server-verified client_key_id.
 * Caller-supplied client_key_id in body or header is ignored for key derivation.
 */
export async function authenticateClient(
  req: Request,
  bodyText: string,
): Promise<AuthenticatedClient> {
  const authHeader = req.headers.get("authorization") ?? "";
  const signature = req.headers.get("x-cvn-signature") ?? "";
  const keyIdHeader = req.headers.get("x-cvn-client-key-id") ?? "";

  if (!authHeader.startsWith("Bearer ")) {
    throw new ClientAuthenticationError("Missing or invalid authorization header");
  }
  if (!signature) {
    throw new ClientAuthenticationError("Missing signature");
  }

  const providedBearer = authHeader.slice(7);

  // 1. Registry-based Multi-Client Identity Path
  const registryJson = Deno.env.get("CVN_CLIENT_CREDENTIALS") ?? "";
  if (registryJson) {
    let registry: any;
    try {
      registry = JSON.parse(registryJson);
    } catch (_e) {
      throw new ClientAuthenticationError("Malformed client credentials registry");
    }

    if (registry.version !== "1.0" || typeof registry.clients !== "object" || registry.clients === null) {
      throw new ClientAuthenticationError("Invalid client credentials registry schema");
    }

    const targetKeyId = keyIdHeader || Deno.env.get("CVN_CLIENT_KEY_ID") || "default_client_key";
    const clientConfig = registry.clients[targetKeyId];
    if (!clientConfig || clientConfig.enabled !== true) {
      throw new ClientAuthenticationError("Client identity not found or disabled");
    }

    const providedBearerHash = await sha256Hex(providedBearer);
    const expectedBearerHash = await sha256Hex(clientConfig.bearer_token);
    if (!timingSafeEqual(providedBearerHash, expectedBearerHash)) {
      throw new ClientAuthenticationError("Invalid bearer token");
    }

    const url = new URL(req.url);
    const canonicalSigText = `${req.method.toUpperCase()}|${url.pathname}|${bodyText}`;
    const expectedSigFull = await hmacSha256Hex(canonicalSigText, clientConfig.hmac_secret);
    const expectedSigBody = await hmacSha256Hex(bodyText, clientConfig.hmac_secret);
    if (
      !timingSafeEqual(signature.toLowerCase(), expectedSigFull.toLowerCase()) &&
      !timingSafeEqual(signature.toLowerCase(), expectedSigBody.toLowerCase())
    ) {
      throw new ClientAuthenticationError("Invalid signature");
    }

    return {
      key_id: targetKeyId,
      source_device_id: clientConfig.source_device_id,
      environment: Deno.env.get("CVN_ENVIRONMENT") || "staging",
    };
  }

  // 2. Single-Client Environment Credential Fallback Path
  const envBearer = Deno.env.get("CVN_BEARER_TOKEN") ?? "";
  const envHmac = Deno.env.get("CVN_HMAC_SECRET") ?? "";
  const serverKeyId = Deno.env.get("CVN_CLIENT_KEY_ID") || "default_client_key";

  if (!envBearer || !envHmac) {
    throw new ClientAuthenticationError("Client authentication unconfigured on server");
  }

  const providedBearerHash = await sha256Hex(providedBearer);
  const envBearerHash = await sha256Hex(envBearer);
  if (!timingSafeEqual(providedBearerHash, envBearerHash)) {
    throw new ClientAuthenticationError("Invalid bearer token");
  }

  const url = new URL(req.url);
  const canonicalSigText = `${req.method.toUpperCase()}|${url.pathname}|${bodyText}`;
  const expectedSigFull = await hmacSha256Hex(canonicalSigText, envHmac);
  const expectedSigBody = await hmacSha256Hex(bodyText, envHmac);
  if (
    !timingSafeEqual(signature.toLowerCase(), expectedSigFull.toLowerCase()) &&
    !timingSafeEqual(signature.toLowerCase(), expectedSigBody.toLowerCase())
  ) {
    throw new ClientAuthenticationError("Invalid signature");
  }

  return {
    key_id: serverKeyId,
    environment: Deno.env.get("CVN_ENVIRONMENT") || "staging",
  };
}
