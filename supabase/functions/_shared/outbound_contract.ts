// Supabase Edge Function Shared Module: cvn.outbound_item.v2 Contract & Canonicalization

export interface CanonicalObject {
  item_kind: string;
  target_agent: string;
  content: Record<string, unknown>;
  task: Record<string, unknown>;
}

export function buildCanonicalObject(
  itemKind: string,
  targetAgent: string | null | undefined,
  content: Record<string, unknown> | null | undefined,
  task: Record<string, unknown> | null | undefined,
): CanonicalObject {
  return {
    item_kind: itemKind || "record_only",
    target_agent: targetAgent || "",
    content: content || {},
    task: task || {},
  };
}

export function validateJsonDomain(val: unknown): void {
  if (val === null || typeof val === "boolean" || typeof val === "string") {
    return;
  }
  if (typeof val === "number") {
    if (!Number.isFinite(val)) {
      throw new Error(
        `Non-finite number ${val} is outside the RFC 8785 JSON domain.`,
      );
    }
    return;
  }
  if (Array.isArray(val)) {
    for (const item of val) {
      validateJsonDomain(item);
    }
    return;
  }
  if (typeof val === "object") {
    for (const key of Object.keys(val as Record<string, unknown>)) {
      if (typeof key !== "string") {
        throw new TypeError(`Object key ${String(key)} is not a string.`);
      }
      validateJsonDomain((val as Record<string, unknown>)[key]);
    }
    return;
  }
  throw new TypeError(
    `Value of type ${typeof val} is outside the RFC 8785 JSON domain.`,
  );
}

export function toCanonicalJson(obj: unknown): string {
  validateJsonDomain(obj);
  if (obj === null || typeof obj !== "object") {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    const items = obj.map((item) => toCanonicalJson(item));
    return `[${items.join(",")}]`;
  }
  const keys = Object.keys(obj as Record<string, unknown>).sort();
  const entries: string[] = [];
  for (const key of keys) {
    const val = (obj as Record<string, unknown>)[key];
    if (val !== undefined) {
      entries.push(`${JSON.stringify(key)}:${toCanonicalJson(val)}`);
    }
  }
  return `{${entries.join(",")}}`;
}

export async function computeCanonicalHash(
  itemKind: string,
  targetAgent: string | null | undefined,
  content: Record<string, unknown> | null | undefined,
  task: Record<string, unknown> | null | undefined,
): Promise<string> {
  const canonicalObj = buildCanonicalObject(
    itemKind,
    targetAgent,
    content,
    task,
  );
  const jsonString = toCanonicalJson(canonicalObj);
  const encoder = new TextEncoder();
  const data = encoder.encode(jsonString);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function isValidHexSha256(hash: string): boolean {
  return typeof hash === "string" && /^[a-f0-9]{64}$/i.test(hash);
}
