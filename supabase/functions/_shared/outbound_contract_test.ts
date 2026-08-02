import { assertEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  computeCanonicalHash,
  toCanonicalJson,
  buildCanonicalObject,
} from "./outbound_contract.ts";

Deno.test("canonical JSON contract test vectors match fixture", async () => {
  const text = await Deno.readTextFile("tests/fixtures/canonical_vectors.json");
  const fixture = JSON.parse(text);

  for (const vec of fixture.vectors) {
    const canonicalObj = buildCanonicalObject(
      vec.item_kind,
      vec.target_agent,
      vec.content,
      vec.task,
    );
    const jsonStr = toCanonicalJson(canonicalObj);
    const hash = await computeCanonicalHash(
      vec.item_kind,
      vec.target_agent,
      vec.content,
      vec.task,
    );

    assertEquals(
      jsonStr,
      vec.expected_canonical_json,
      `Vector '${vec.name}' JSON mismatch`,
    );
    assertEquals(hash, vec.expected_hash, `Vector '${vec.name}' hash mismatch`);
  }
});
