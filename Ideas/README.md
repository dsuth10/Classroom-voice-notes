# CVN Broker — MVP

Broker for Classroom Voice Notes (CVN) agent task dispatch. Built on the
existing Supabase project; adds new tables, an append-only event log, a
pgmq queue, a stored procedure, and a single Edge Function
(`cvn-submit-task`). No claim/complete/fail yet — that's milestone 2.

## Files

- `migrations/001_cvn_broker_mvp.sql` — DDL + stored procedure
- `edge-functions/cvn-submit-task/index.ts` — Deno Edge Function
- `README.md` — this file

## What it does (milestone 1)

CVN (or a test script) submits a fake non-sensitive task. The broker:

1. Verifies the Bearer token.
2. Verifies the HMAC-SHA256 signature.
3. Rejects stale `signed_at` (>5 min old).
4. Rejects duplicate `idempotency_key` (409).
5. Validates the schema (`cvn.agent_task.v1`).
6. Atomically inserts into `cvn_tasks` + `cvn_task_events` + enqueues
   to pgmq.
7. Returns `{accepted, task_id, status_url, msg_id}`.

No agent processes the task yet. No callback exists. No sensitive data
is involved.

## Pre-deployment setup

### 1. Apply the migration

```bash
# Local link first
supabase link --project-ref <your-project-ref>

# Apply the migration
supabase db push
# Or apply directly:
psql "$DATABASE_URL" -f migrations/001_cvn_broker_mvp.sql
```

### 2. Generate secrets

```bash
# HMAC secret (32 bytes random, hex)
openssl rand -hex 32

# Bearer token (32 bytes random, hex)
openssl rand -hex 32
```

### 3. Set Edge Function secrets

In Supabase Dashboard → Edge Functions → Secrets:

- `CVN_HMAC_SECRET` — the HMAC secret from step 2
- `CVN_BEARER_TOKEN` — the bearer token from step 2

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are auto-set.

### 4. Deploy the Edge Function

```bash
supabase functions deploy cvn-submit-task --no-verify-jwt
```

### 5. Store the secrets in CVN's local keychain

On the Windows classroom machine:

```python
import keyring
keyring.set_password("ClassroomVoiceNotes", "cvn_hmac_secret", "<HMAC_SECRET>")
keyring.set_password("ClassroomVoiceNotes", "cvn_bearer_token", "<BEARER_TOKEN>")
```

CVN's `settings.json` will reference these by name (not value):

```json
{
  "external_agent": {
    "endpoint_url": "https://<project-ref>.supabase.co/functions/v1/cvn-submit-task",
    "hmac_secret_ref": "cvn_hmac_secret",
    "bearer_token_ref": "cvn_bearer_token"
  }
}
```

## Test milestone

A small test script to verify the broker works end-to-end (no agent
needed).

### 1. Build a fake task payload (Python)

```python
import datetime
import hashlib
import hmac
import json
import secrets

HMAC_SECRET = "<your HMAC secret>"
BEARER_TOKEN = "<your bearer token>"
ENDPOINT = "https://<project-ref>.supabase.co/functions/v1/cvn-submit-task"

now = datetime.datetime.now(datetime.timezone.utc)
task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()

payload = {
    "schema_version": "cvn.agent_task.v1",
    "task_id": task_id,
    "created_at": now.isoformat(),
    "source": "classroom_voice_notes",
    "source_device_id": "test-script-001",
    "target_agent": "hermes",
    "privacy": {
        "classification": "non_sensitive",
        "policy_gate_version": "1.0.0",
        "checks_passed": [
            "category_agent_task",
            "no_student_registry_match",
            "no_forbidden_terms",
            "no_audio_attached",
            "no_local_file_path",
        ],
    },
    "task": {
        "title": "Test task — broker MVP",
        "instructions": "This is a fake non-sensitive task to verify the broker MVP.",
        "priority": "normal",
    },
    "redactions_applied": [],
    "signed_at": now.isoformat(),
    "nonce": secrets.token_hex(16),
    "idempotency_key": "test-" + secrets.token_hex(8),
}

body = json.dumps(payload, separators=(",", ":"))
signature = hmac.new(
    HMAC_SECRET.encode(), body.encode(), hashlib.sha256
).hexdigest()
```

### 2. POST it

```bash
curl -X POST "$ENDPOINT" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "x-cvn-signature: $signature" \
  -H "Content-Type: application/json" \
  --data "$body"
```

Expected response:

```json
{
  "accepted": true,
  "task_id": "CVN-20260707-123045-A1B2",
  "status_url": "/functions/v1/cvn-status/CVN-20260707-123045-A1B2",
  "msg_id": 1
}
```

### 3. Verify in Supabase

In Supabase Dashboard → SQL Editor:

```sql
-- 1. Task is in cvn_tasks
SELECT task_id, status, target_agent, privacy_classification, payload_hash
FROM public.cvn_tasks;

-- 2. Event is in cvn_task_events
SELECT event_type, actor, event_at
FROM public.cvn_task_events
ORDER BY event_at DESC LIMIT 5;

-- 3. Queue message exists in pgmq
SELECT msg_id, message, enqueued_at, vt
FROM pgmq.q_cvn_tasks_queue
ORDER BY msg_id;
```

Expected: one row in each table, with matching `task_id`.

### 4. Negative tests

- Replay the same `idempotency_key` → expect 409 +
  `error: duplicate_idempotency_key`
- Replay with stale `signed_at` (10 min ago) → expect 401
- Tamper with body (signature no longer matches) → expect 401
- Wrong bearer token → expect 401
- Missing required field (e.g., `task.instructions`) → expect 400 with
  `error: schema_validation_failed`

## Next milestone

Once milestone 1 passes:

- Add `cvn-claim-task`, `cvn-complete-task`, `cvn-fail-task` Edge
  Functions.
- Add `pg_cron` reaper for stale `claimed` tasks.
- Add the VPS `watch_inbox.py` poller.
- Wire up CVN-side dispatcher + outbox.

## Open questions resolved

- **Single agent or multi-agent?** Single poller, internal routing on
  `target_agent`.
- **Polling or callbacks?** Polling (CVN polls
  `/cvn-status/{task_id}` every 15-30s for 2 min, then 2-5 min).
- **Retention?** 30d payload, 90d metadata, 90d events, indefinite
  aggregate stats.
- **Safe-task generation?** Separate Ollama call (Call 1 = classify,
  Call 2 = safe_external_task).
- **Outbox expiry?** 7d, backoff 3/9/27/81/243s then hourly, after 5
  failures move to local DLQ.

## Security model summary

- Outbound-only from the classroom machine.
- No inbound tunnel to the classroom machine.
- Hardcoded allowlist of destination domains (CVN config).
- HMAC-SHA256 request signing (5-min stale window).
- Bearer token in `Authorization` header.
- Idempotency key for safe retries.
- Append-only audit log (DB trigger + RLS).
- OS keychain for local secret storage (Windows Credential Manager via
  `keyring`).
