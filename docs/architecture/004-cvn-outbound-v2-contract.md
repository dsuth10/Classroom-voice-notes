# ADR 004: CVN Outbound Item v2 Specification & Canonicalization Rules

**Status:** Approved  
**Date:** 2026-08-01  
**Schema Version:** `cvn.outbound_item.v2`

---

## 1. Overview

This document specifies the structure, field constraints, lifecycle statuses, and deterministic canonicalization rules for the `cvn.outbound_item.v2` protocol. All local clients (desktop app) and remote services (Supabase Edge Functions, Workers) must strictly adhere to this contract.

---

## 2. Canonical Content Structure & Rules (RFC 8785)

The canonical content object forms the exact payload data assessed, hashed, and authorized for release:

```json
{
  "content": {},
  "item_kind": "record_only",
  "target_agent": "openclaw",
  "task": {}
}
```

### Approved RFC 8785 Packages & Versions
- **Python**: `rfc8785==0.1.4` (`app/destinations/canonical_json.py`)
- **TypeScript / Deno**: `npm:canonicalize@2.0.0` (`supabase/functions/_shared/outbound_contract.ts`)

### Rules:
1. **Field Normalization**:
   - `item_kind`: Default to `"record_only"` if empty or falsy.
   - `target_agent`: Absent or `null` MUST be normalized to `""`.
   - `content`: Absent or `null` MUST be normalized to `{}`.
   - `task`: Absent or `null` MUST be normalized to `{}`.
2. **RFC 8785 Canonical JSON Formatting**:
   - **Key Sorting**: Object keys are sorted in UTF-16 code unit order (lexicographical order), including non-BMP Unicode keys.
   - **Number Formatting**: Standard ECMAScript IEEE-754 / RFC 8785 format (`1.0` -> `1`, `-0.0` -> `0`, `1e21` -> `1e+21`, `1e-7` -> `1e-7`).
   - **Array Preservation**: Element ordering in arrays is preserved as-is.
   - **UTF-8 Encoding**: UTF-8 bytes with zero unnecessary whitespace (delimiters `,` and `:` without spaces).
   - **Domain Validation**: Values outside the JSON domain (`NaN`, positive/negative `Infinity`, non-string object keys, unsupported object types) MUST be rejected before serialization.
3. **Transport Field Isolation**:
   - Retry fields (`nonce`, `signature`, `signed_at`, `idempotency_key`, transport wrapper hash) MUST NOT be included in the approved content hash calculation.
4. **SHA-256 Hashing**:
   - The SHA-256 hash is computed directly over the UTF-8 encoded RFC 8785 canonical JSON string.
   - Hash output format: Lowercase 64-character hexadecimal string.


---

## 3. Top-Level Payload Schema

```json
{
  "schema_version": "cvn.outbound_item.v2",
  "item_id": "CVNI-20260801-123456-ABCDEF",
  "created_at": "2026-08-01T12:00:00.000Z",
  "source": "classroom_voice_notes",
  "source_device_id": "cvn-device-uuid",
  "item_kind": "record_only | agent_task",
  "target_agent": "openclaw",
  "content": {},
  "task": {},
  "privacy": {
    "automatic_classification": "non_sensitive | sensitive_pii | safeguarding | medical",
    "risk_level": "low | medium | high",
    "findings": [],
    "policy_gate_version": "2.0.0",
    "release_basis": "automatic_policy | human_approval | trusted_mode",
    "approval": {
      "approved_at": "2026-08-01T12:05:00.000Z",
      "approved_content_hash": "64-char-hex",
      "reviewer_type": "local_user | trusted_system"
    }
  },
  "content_hash": "64-char-hex",
  "signed_at": "2026-08-01T12:05:01.000Z",
  "nonce": "uuid",
  "idempotency_key": "uuid"
}
```

---

## 4. Supported Values & Limits

- **item_kind**: `record_only`, `agent_task`
- **supported target_agents**: `openclaw` (Hermes is unpermitted until explicit implementation).
- **release_basis**: `automatic_policy`, `human_approval`, `trusted_mode`
- **Max Payload Size**: 512 KB

---

## 5. Lifecycle States

| State | Scope | Description |
|---|---|---|
| `awaiting_review` | Local | Item captured and pending human review |
| `approved_pending_enqueue` | Local | Approved by human/trusted mode, awaiting local outbox enqueue |
| `submitted` | Remote Queue | Broker accepted and enqueued |
| `claimed` | Remote Worker | Leased to worker for consumer processing |
| `completed` | Terminal | Successfully exported/executed by target worker |
| `failed_retryable` | Remote Worker | Execution failed, eligible for retry |
| `failed_permanent` | Terminal | Execution failed permanently, moved to dead letter |
| `dead_letter` | Remote/Local | Max retries exceeded, pending manual operator action |
| `expired` | Terminal | TTL exceeded without consumption |
