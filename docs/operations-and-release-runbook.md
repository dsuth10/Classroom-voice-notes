# Outbound Sharing Operations & Release Runbook

## Overview
This runbook defines standard operational procedures, privacy controls, emergency disable steps, and rollback routines for Classroom Voice Notes (CVN) Outbound Sharing v2.

---

## 1. Sharing Modes & Safety Defaults

- `off` (Default): All voice capture, classification, and notes remain strictly local on the client device.
- `safe_auto`: Automatically queues non-sensitive v1 tasks passing policy gate checks.
- `review_all`: Places all captured items into human review before any outbound release.
- `trusted_auto`: Releases low-risk, explicitly permitted items automatically using truthful `release_basis = trusted_mode`. High-risk or policy failures immediately pause for human review.

---

## 2. Emergency Sharing Disable

In the event of a security incident, data leakage suspicion, or network outage:

1. **Client Desktop App:**
   - Go to **Settings $\rightarrow$ Outbound Sharing**.
   - Toggle **Sharing Mode** to `Off`.
   - All pending outbox tasks immediately halt local submission.

2. **Remote Edge / Supabase Broker:**
   - Rotate `CVN_BEARER_TOKEN` and `CVN_HMAC_SECRET` in Supabase Environment Secrets.
   - All incoming submissions with legacy tokens/signatures will instantly be rejected with `401 unauthorized` / `401 invalid_signature`.

---

## 3. Data Privacy & Retention Policy

- **No Unencrypted Secrets:** Credentials, HMAC keys, and bearer tokens are stored in the OS Keyring or server secret store, never in plain JSON.
- **Payload Limits:** Server rejects payloads > 512 KB (`413 body_too_large`).
- **No Log Leakage:** Transcripts, signatures, full vault paths, and student PII are excluded from metrics and application logs.
- **Retention Purging:** `OutboundReviewStore.purge_expired_reviews(retention_days=30)` automatically purges terminal review records older than 30 days.

---

## 4. Operational Troubleshooting

| Symptom | Root Cause | Remediation |
|---|---|---|
| Edge returns `400 content_hash_mismatch` | Client content altered post-hashing | Re-assess item and generate fresh canonical hash |
| Edge returns `413 body_too_large` | Payload exceeds 512 KB limit | Truncate transcript/instructions before submission |
| Edge returns `409 duplicate_idempotency_key` | Duplicate task submission | Idempotency guard working; inspect original task status |
| Worker returns `InvalidTaskPayload` | `record_only` item sent to agent adapter | Confirm worker routing branches `record_only` to RecordConsumer |

---

## 5. System Rollback Procedure

- **Desktop App:** Revert executable binary to previous signed version. Local SQLite databases (`outbound_review.db`, `outbound_records.db`) preserve existing rows.
- **Edge Functions:** Redeploy prior function version using `supabase functions deploy`.
- **Database Migrations:** SQL migrations are additive forward-only migrations. Table structures retain backwards compatibility.
