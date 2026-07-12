// supabase/functions/_shared/broker_auth.ts

export type AuthenticatedWorker = {
  key_id: string;
  allowed_targets: string[];
  allowed_worker_ids: string[];
  legacy: boolean;
};

// Custom error for authentication failure to allow standard response
export class AuthenticationError extends Error {
  constructor(message: string = "Unauthorized") {
    super(message);
    this.name = "AuthenticationError";
  }
}

const MAX_REGISTRY_SIZE_BYTES = 10 * 1024; // 10KB max for credentials JSON

// Use a fast SHA-256 for mitigating length-extension/timing on bearer token
export async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
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

export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export async function authenticateWorker(
  req: Request,
  rawBodyOrCanonicalString: string
): Promise<AuthenticatedWorker> {
  const authHeader = req.headers.get("authorization") ?? "";
  const signature = req.headers.get("x-cvn-signature") ?? "";
  const keyId = req.headers.get("x-cvn-key-id") ?? "";

  if (!authHeader.startsWith("Bearer ")) {
    throw new AuthenticationError("Missing or invalid authorization header");
  }
  if (!signature) {
    throw new AuthenticationError("Missing signature");
  }

  const providedBearer = authHeader.slice(7);

  // 1. Legacy Fallback Path
  if (!keyId) {
    const legacyBearer = Deno.env.get("AGENT_BROKER_BEARER_TOKEN") ?? "";
    const legacyHmac = Deno.env.get("AGENT_BROKER_HMAC_SECRET") ?? "";

    if (!legacyBearer || !legacyHmac) {
      throw new AuthenticationError("Legacy authentication disabled");
    }

    // Hash bearers before timing-safe equal
    const providedHash = await sha256Hex(providedBearer);
    const legacyHash = await sha256Hex(legacyBearer);

    if (!timingSafeEqual(providedHash, legacyHash)) {
      throw new AuthenticationError("Invalid legacy bearer");
    }

    const expectedSig = await hmacSha256Hex(rawBodyOrCanonicalString, legacyHmac);
    if (!timingSafeEqual(signature.toLowerCase(), expectedSig.toLowerCase())) {
      throw new AuthenticationError("Invalid legacy signature");
    }

    console.warn("WARN: Legacy missing-key-ID fallback used. This path is deprecated.");

    return {
      key_id: "legacy-hermes-key",
      allowed_targets: ["hermes"],
      allowed_worker_ids: [], // empty implies no strict check, or we can check later
      legacy: true
    };
  }

  // 2. Multi-Worker Identity Path
  if (keyId.length > 64 || !/^[a-zA-Z0-9_-]+$/.test(keyId)) {
    throw new AuthenticationError("Invalid key ID format");
  }

  const registryJson = Deno.env.get("AGENT_BROKER_WORKER_CREDENTIALS") ?? "";
  if (!registryJson) {
    throw new AuthenticationError("Worker registry absent");
  }

  if (new TextEncoder().encode(registryJson).length > MAX_REGISTRY_SIZE_BYTES) {
    throw new AuthenticationError("Registry exceeds maximum size");
  }

  let registry: any;
  try {
    registry = JSON.parse(registryJson);
  } catch (e) {
    throw new AuthenticationError("Malformed registry JSON");
  }

  if (registry.version !== "1.0" || typeof registry.keys !== "object" || registry.keys === null) {
    throw new AuthenticationError("Unsupported or invalid registry schema");
  }

  const keyConfig = registry.keys[keyId];
  if (!keyConfig) {
    throw new AuthenticationError("Unknown key ID");
  }

  // Strict validation of the entry
  if (keyConfig.enabled !== true) {
    throw new AuthenticationError("Key disabled");
  }

  if (
    typeof keyConfig.bearer_token !== "string" ||
    typeof keyConfig.hmac_secret !== "string" ||
    !Array.isArray(keyConfig.allowed_targets) ||
    keyConfig.allowed_targets.length === 0 ||
    !Array.isArray(keyConfig.allowed_worker_ids) ||
    keyConfig.allowed_worker_ids.length === 0
  ) {
    throw new AuthenticationError("Invalid key configuration in registry");
  }

  // Validate fields for unknown properties (fail closed)
  const allowedKeys = ["enabled", "bearer_token", "hmac_secret", "allowed_targets", "allowed_worker_ids"];
  for (const k of Object.keys(keyConfig)) {
    if (!allowedKeys.includes(k)) {
      throw new AuthenticationError("Registry entry contains unknown fields");
    }
  }

  // Hash before timing safe equal
  const providedBearerHash = await sha256Hex(providedBearer);
  const expectedBearerHash = await sha256Hex(keyConfig.bearer_token);

  let isAuthenticated = true;

  if (!timingSafeEqual(providedBearerHash, expectedBearerHash)) {
    isAuthenticated = false;
  }

  const expectedSig = await hmacSha256Hex(rawBodyOrCanonicalString, keyConfig.hmac_secret);
  if (!timingSafeEqual(signature.toLowerCase(), expectedSig.toLowerCase())) {
    isAuthenticated = false;
  }

  if (!isAuthenticated) {
    throw new AuthenticationError("Invalid credentials");
  }

  return {
    key_id: keyId,
    allowed_targets: keyConfig.allowed_targets,
    allowed_worker_ids: keyConfig.allowed_worker_ids,
    legacy: false
  };
}
