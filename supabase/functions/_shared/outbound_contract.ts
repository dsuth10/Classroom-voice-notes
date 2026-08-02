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
  task: Record<string, unknown> | null | undefined
): CanonicalObject {
  return {
    item_kind: itemKind || "record_only",
    target_agent: targetAgent || "",
    content: content || {},
    task: task || {},
  };
}

export function recursiveSortObject(obj: unknown): unknown {
  if (obj === null || typeof obj !== "object") {
    return obj;
  }
  if (Array.isArray(obj)) {
    return obj.map(recursiveSortObject);
  }
  const sortedKeys = Object.keys(obj as Record<string, unknown>).sort();
  const result: Record<string, unknown> = {};
  for (const key of sortedKeys) {
    result[key] = recursiveSortObject((obj as Record<string, unknown>)[key]);
  }
  return result;
}

export function toCanonicalJson(obj: unknown): string {
  const sorted = recursiveSortObject(obj);
  return JSON.stringify(sorted);
}

export async function computeCanonicalHash(
  itemKind: string,
  targetAgent: string | null | undefined,
  content: Record<string, unknown> | null | undefined,
  task: Record<string, unknown> | null | undefined
): Promise<string> {
  const canonicalObj = buildCanonicalObject(itemKind, targetAgent, content, task);
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
