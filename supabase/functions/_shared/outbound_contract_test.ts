// supabase/functions/_shared/outbound_contract_test.ts
import {
  assertEquals,
  assertRejects,
} from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  authenticateWorker,
  AuthenticationError,
  hmacSha256Hex,
} from "./broker_auth.ts";
import {
  authenticateClient,
  ClientAuthenticationError,
} from "./client_auth.ts";

function createMockSupabaseClient(seenSet: Set<string> = new Set()) {
  return {
    rpc: (name: string, args: any) => {
      if (name === "cvn_register_request_nonce") {
        const key = `${args.p_credential_type}:${args.p_key_id}:${args.p_nonce}`;
        const nowSeconds = Math.floor(Date.now() / 1000);
        if (
          Math.abs(nowSeconds - args.p_timestamp) > args.p_ttl_seconds ||
          seenSet.has(key)
        ) {
          return Promise.resolve({ data: false, error: null });
        }
        seenSet.add(key);
        return Promise.resolve({ data: true, error: null });
      }
      return Promise.resolve({ data: null, error: { message: "Unknown RPC" } });
    },
  };
}

Deno.test("Worker Auth — Valid 5-Element HMAC Request", async () => {
  const secret = "test-secret-123";
  const registry = {
    version: "1.0",
    keys: {
      "worker-1": {
        enabled: true,
        bearer_token: "test-bearer",
        hmac_secret: secret,
        allowed_targets: ["openclaw"],
        allowed_worker_ids: ["worker-1"],
        allowed_kinds: ["record_only", "agent_task"],
      },
    },
  };
  Deno.env.set("AGENT_BROKER_WORKER_CREDENTIALS", JSON.stringify(registry));

  const path = "/functions/v1/cvn-claim-outbound-item";
  const now = Math.floor(Date.now() / 1000).toString();
  const nonce = "nonce-" + Math.random().toString(36).substring(2);
  const body = JSON.stringify({ worker_id: "worker-1" });

  const canonical = `POST|${path}|${now}|${nonce}|${body}`;
  const sig = await hmacSha256Hex(canonical, secret);

  const req = new Request(`https://test.supabase.co${path}`, {
    method: "POST",
    headers: {
      Authorization: "Bearer test-bearer",
      "X-CVN-Key-Id": "worker-1",
      "X-CVN-Signature": sig,
      "X-CVN-Timestamp": now,
      "X-CVN-Nonce": nonce,
      "Content-Type": "application/json",
    },
  });

  const mockDb = createMockSupabaseClient();
  const worker = await authenticateWorker(req, body, mockDb);
  assertEquals(worker.key_id, "worker-1");
  assertEquals(worker.allowed_targets, ["openclaw"]);
  assertEquals(worker.allowed_kinds, ["record_only", "agent_task"]);
});

Deno.test("Worker Auth — Rejects Missing Mandatory Headers", async () => {
  const req = new Request(
    "https://test.supabase.co/functions/v1/cvn-claim-outbound-item",
    {
      method: "POST",
      headers: {
        Authorization: "Bearer test-bearer",
      },
    },
  );

  await assertRejects(
    async () => {
      await authenticateWorker(req, "{}");
    },
    AuthenticationError,
    "Missing signature",
  );
});

Deno.test("Worker Auth — Rejects Stale and Future Timestamps", async () => {
  const secret = "test-secret-123";
  const registry = {
    version: "1.0",
    keys: {
      "worker-1": {
        enabled: true,
        bearer_token: "test-bearer",
        hmac_secret: secret,
        allowed_targets: ["openclaw"],
        allowed_worker_ids: ["worker-1"],
        allowed_kinds: ["record_only"],
      },
    },
  };
  Deno.env.set("AGENT_BROKER_WORKER_CREDENTIALS", JSON.stringify(registry));

  const path = "/functions/v1/cvn-claim-outbound-item";
  const staleTime = (Math.floor(Date.now() / 1000) - 600).toString();
  const nonce = "nonce-stale-123";
  const body = "{}";

  const canonical = `POST|${path}|${staleTime}|${nonce}|${body}`;
  const sig = await hmacSha256Hex(canonical, secret);

  const req = new Request(`https://test.supabase.co${path}`, {
    method: "POST",
    headers: {
      Authorization: "Bearer test-bearer",
      "X-CVN-Key-Id": "worker-1",
      "X-CVN-Signature": sig,
      "X-CVN-Timestamp": staleTime,
      "X-CVN-Nonce": nonce,
      "Content-Type": "application/json",
    },
  });

  await assertRejects(
    async () => {
      await authenticateWorker(req, body);
    },
    AuthenticationError,
    "Stale or invalid request timestamp",
  );
});

Deno.test("Worker Auth — Rejects Replayed Nonces via DB RPC", async () => {
  const secret = "test-secret-123";
  const registry = {
    version: "1.0",
    keys: {
      "worker-1": {
        enabled: true,
        bearer_token: "test-bearer",
        hmac_secret: secret,
        allowed_targets: ["openclaw"],
        allowed_worker_ids: ["worker-1"],
        allowed_kinds: ["record_only"],
      },
    },
  };
  Deno.env.set("AGENT_BROKER_WORKER_CREDENTIALS", JSON.stringify(registry));

  const path = "/functions/v1/cvn-claim-outbound-item";
  const now = Math.floor(Date.now() / 1000).toString();
  const nonce = "nonce-replay-unique-999";
  const body = JSON.stringify({ worker_id: "worker-1" });

  const canonical = `POST|${path}|${now}|${nonce}|${body}`;
  const sig = await hmacSha256Hex(canonical, secret);

  const mockDb = createMockSupabaseClient();

  const makeReq = () =>
    new Request(`https://test.supabase.co${path}`, {
      method: "POST",
      headers: {
        Authorization: "Bearer test-bearer",
        "X-CVN-Key-Id": "worker-1",
        "X-CVN-Signature": sig,
        "X-CVN-Timestamp": now,
        "X-CVN-Nonce": nonce,
        "Content-Type": "application/json",
      },
    });

  // First request succeeds
  const firstPass = await authenticateWorker(makeReq(), body, mockDb);
  assertEquals(firstPass.key_id, "worker-1");

  // Immediate second request with identical nonce is rejected by DB RPC
  await assertRejects(
    async () => {
      await authenticateWorker(makeReq(), body, mockDb);
    },
    AuthenticationError,
    "Nonce already used or timestamp expired",
  );
});

Deno.test(
  "Worker Auth — Rejects Missing allowed_kinds in Registry",
  async () => {
    const secret = "test-secret-123";
    const registry = {
      version: "1.0",
      keys: {
        "invalid-worker": {
          enabled: true,
          bearer_token: "test-bearer",
          hmac_secret: secret,
          allowed_targets: ["openclaw"],
          allowed_worker_ids: ["invalid-worker"],
          // allowed_kinds intentionally omitted
        },
      },
    };
    Deno.env.set("AGENT_BROKER_WORKER_CREDENTIALS", JSON.stringify(registry));

    const path = "/functions/v1/cvn-claim-outbound-item";
    const now = Math.floor(Date.now() / 1000).toString();
    const nonce = "nonce-" + Math.random().toString(36).substring(2);
    const body = JSON.stringify({ worker_id: "invalid-worker" });

    const canonical = `POST|${path}|${now}|${nonce}|${body}`;
    const sig = await hmacSha256Hex(canonical, secret);

    const req = new Request(`https://test.supabase.co${path}`, {
      method: "POST",
      headers: {
        Authorization: "Bearer test-bearer",
        "X-CVN-Key-Id": "invalid-worker",
        "X-CVN-Signature": sig,
        "X-CVN-Timestamp": now,
        "X-CVN-Nonce": nonce,
        "Content-Type": "application/json",
      },
    });

    await assertRejects(
      async () => {
        await authenticateWorker(req, body);
      },
      AuthenticationError,
      "allowed_kinds is required",
    );
  },
);

Deno.test(
  "Client Auth — Valid 5-Element Request and Replay Rejection",
  async () => {
    Deno.env.set("CVN_BEARER_TOKEN", "client-bearer-123");
    Deno.env.set("CVN_HMAC_SECRET", "client-hmac-456");
    Deno.env.set("CVN_CLIENT_KEY_ID", "desktop-client-1");

    const path = "/functions/v1/cvn-submit-outbound-item";
    const now = Math.floor(Date.now() / 1000).toString();
    const nonce = "nonce-client-9999";
    const body = JSON.stringify({ item_id: "CVNI-TEST-1" });

    const canonical5 = `POST|${path}|${now}|${nonce}|${body}`;
    const sig5 = await hmacSha256Hex(canonical5, "client-hmac-456");

    const mockDb = createMockSupabaseClient();

    const makeValidReq = () =>
      new Request(`https://test.supabase.co${path}`, {
        method: "POST",
        headers: {
          Authorization: "Bearer client-bearer-123",
          "X-CVN-Client-Key-Id": "desktop-client-1",
          "X-CVN-Signature": sig5,
          "X-CVN-Timestamp": now,
          "X-CVN-Nonce": nonce,
          "Content-Type": "application/json",
        },
      });

    const client = await authenticateClient(makeValidReq(), body, mockDb);
    assertEquals(client.key_id, "desktop-client-1");

    // Replay attempt rejected
    await assertRejects(
      async () => {
        await authenticateClient(makeValidReq(), body, mockDb);
      },
      ClientAuthenticationError,
      "Nonce already used or timestamp expired",
    );
  },
);

Deno.test(
  "Client Auth — Retries with Fresh Request Nonce Succeed",
  async () => {
    Deno.env.set("CVN_BEARER_TOKEN", "client-bearer-123");
    Deno.env.set("CVN_HMAC_SECRET", "client-hmac-456");

    const path = "/functions/v1/cvn-submit-task";
    const body = JSON.stringify({ task_id: "CVN-20260802-120000-A1B2" });

    const mockDb = createMockSupabaseClient();

    // Initial Attempt (Attempt 1)
    const now1 = Math.floor(Date.now() / 1000).toString();
    const reqNonce1 = "req-nonce-attempt-1";
    const canonical1 = `POST|${path}|${now1}|${reqNonce1}|${body}`;
    const sig1 = await hmacSha256Hex(canonical1, "client-hmac-456");

    const req1 = new Request(`https://test.supabase.co${path}`, {
      method: "POST",
      headers: {
        Authorization: "Bearer client-bearer-123",
        "X-CVN-Client-Key-Id": "desktop-client-1",
        "X-CVN-Signature": sig1,
        "X-CVN-Timestamp": now1,
        "X-CVN-Nonce": reqNonce1,
        "Content-Type": "application/json",
      },
    });

    const res1 = await authenticateClient(req1, body, mockDb);
    assertEquals(res1.key_id, "desktop-client-1");

    // Retry Attempt (Attempt 2) with Fresh Request Nonce
    const now2 = Math.floor(Date.now() / 1000).toString();
    const reqNonce2 = "req-nonce-attempt-2";
    const canonical2 = `POST|${path}|${now2}|${reqNonce2}|${body}`;
    const sig2 = await hmacSha256Hex(canonical2, "client-hmac-456");

    const req2 = new Request(`https://test.supabase.co${path}`, {
      method: "POST",
      headers: {
        Authorization: "Bearer client-bearer-123",
        "X-CVN-Client-Key-Id": "desktop-client-1",
        "X-CVN-Signature": sig2,
        "X-CVN-Timestamp": now2,
        "X-CVN-Nonce": reqNonce2,
        "Content-Type": "application/json",
      },
    });

    const res2 = await authenticateClient(req2, body, mockDb);
    assertEquals(res2.key_id, "desktop-client-1");
  },
);
