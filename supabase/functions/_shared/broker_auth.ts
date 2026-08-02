// supabase/functions/_shared/broker_auth.ts

export type AuthenticatedWorker = {
  key_id: string;
  allowed_targets: string[];
  allowed_worker_ids: string[];
  allowed_kinds: string[];
  max_visibility_timeout: number;
  batch_limit: number;
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
const MAX_TIMESTAMP_AGE_SECONDS = 300; // 5 minutes freshness window

// In-memory nonce cache with TTL for replay protection
const seenNonces = new Map<string, number>();

function pruneSeenNonces(nowSeconds: number) {
  for (const [nonce, ts] of seenNonces.entries()) {
    if (nowSeconds - ts > MAX_TIMESTAMP_AGE_SECONDS * 2) {
      seenNonces.delete(nonce);
    }
  }
}

// Fast SHA-256 for mitigating length-extension/timing on bearer token
export async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(s),
  );
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function hmacSha256Hex(
  body: string,
  secret: string,
): Promise<string> {
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
  rawBodyOrCanonicalString: string,
): Promise<AuthenticatedWorker> {
  const authHeader = req.headers.get("authorization") ?? "";
  const signature = req.headers.get("x-cvn-signature") ?? "";
  const keyId = req.headers.get("x-cvn-key-id") ?? "";
  const timestampStr = req.headers.get("x-cvn-timestamp") ?? "";
  const nonce = req.headers.get("x-cvn-nonce") ?? "";

  if (!authHeader.startsWith("Bearer ")) {
    throw new AuthenticationError("Missing or invalid authorization header");
  }
  if (!signature) {
    throw new AuthenticationError("Missing signature");
  }
  if (!keyId) {
    throw new AuthenticationError("Missing key ID");
  }
  if (!timestampStr) {
    throw new AuthenticationError("Missing timestamp header");
  }
  if (!nonce) {
    throw new AuthenticationError("Missing nonce header");
  }

  // 1. Timestamp Freshness Check
  const nowSeconds = Math.floor(Date.now() / 1000);
  const reqTimestamp = parseInt(timestampStr, 10);
  if (
    isNaN(reqTimestamp) ||
    Math.abs(nowSeconds - reqTimestamp) > MAX_TIMESTAMP_AGE_SECONDS
  ) {
    throw new AuthenticationError("Stale or invalid request timestamp");
  }

  // 2. Nonce Replay Protection Check
  pruneSeenNonces(nowSeconds);
  const nonceKey = `${keyId}:${nonce}`;
  if (seenNonces.has(nonceKey)) {
    throw new AuthenticationError("Nonce already used");
  }

  const providedBearer = authHeader.slice(7);

  // 3. Multi-Worker Identity & Registry Validation
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

  if (
    registry.version !== "1.0" ||
    typeof registry.keys !== "object" ||
    registry.keys === null
  ) {
    throw new AuthenticationError("Unsupported or invalid registry schema");
  }

  const keyConfig = registry.keys[keyId];
  if (!keyConfig) {
    throw new AuthenticationError("Unknown key ID");
  }

  if (keyConfig.enabled !== true) {
    throw new AuthenticationError("Key disabled");
  }

  // Strict Fail-Closed Validation of Permission Arrays
  if (
    !Array.isArray(keyConfig.allowed_kinds) ||
    keyConfig.allowed_kinds.length === 0
  ) {
    throw new AuthenticationError(
      "Invalid key configuration: allowed_kinds is required and must be non-empty array",
    );
  }
  const allowedKinds = keyConfig.allowed_kinds;

  if (
    typeof keyConfig.bearer_token !== "string" ||
    typeof keyConfig.hmac_secret !== "string" ||
    !Array.isArray(keyConfig.allowed_targets) ||
    keyConfig.allowed_targets.length === 0 ||
    !Array.isArray(keyConfig.allowed_worker_ids) ||
    keyConfig.allowed_worker_ids.length === 0
  ) {
    throw new AuthenticationError(
      "Invalid key configuration or empty permission list",
    );
  }

  const allowedKeys = [
    "enabled",
    "bearer_token",
    "hmac_secret",
    "allowed_targets",
    "allowed_worker_ids",
    "allowed_kinds",
    "max_visibility_timeout",
    "batch_limit",
  ];
  for (const k of Object.keys(keyConfig)) {
    if (!allowedKeys.includes(k)) {
      throw new AuthenticationError("Registry entry contains unknown fields");
    }
  }

  // 4. Bearer Hash Verification
  const providedBearerHash = await sha256Hex(providedBearer);
  const expectedBearerHash = await sha256Hex(keyConfig.bearer_token);
  if (!timingSafeEqual(providedBearerHash, expectedBearerHash)) {
    throw new AuthenticationError("Invalid credentials");
  }

  // 5. 5-Element Canonical HMAC Signature Verification: METHOD|PATH|TIMESTAMP|NONCE|BODY
  const url = new URL(req.url);
  const canonicalString = `${req.method.toUpperCase()}|${url.pathname}|${timestampStr}|${nonce}|${rawBodyOrCanonicalString}`;
  const expectedSig = await hmacSha256Hex(
    canonicalString,
    keyConfig.hmac_secret,
  );

  if (!timingSafeEqual(signature.toLowerCase(), expectedSig.toLowerCase())) {
    throw new AuthenticationError("Invalid signature");
  }

  // Record nonce only after signature and credentials are fully verified
  seenNonces.set(nonceKey, nowSeconds);

  return {
    key_id: keyId,
    allowed_targets: keyConfig.allowed_targets,
    allowed_worker_ids: keyConfig.allowed_worker_ids,
    allowed_kinds: allowedKinds,
    max_visibility_timeout: keyConfig.max_visibility_timeout || 300,
    batch_limit: keyConfig.batch_limit || 1,
    legacy: false,
  };
}
