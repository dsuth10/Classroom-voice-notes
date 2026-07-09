# Classroom Voice Notes — External Agent Broker Project Brief

**Audience:** Coding agent  
**Project:** Classroom Voice Notes external agent dispatch integration  
**Current phase:** Supabase Broker Milestone 1 complete in production; Classroom Voice Notes app-side integration is next  
**Security note:** This document intentionally contains no secrets, access tokens, HMAC values, bearer tokens, database passwords, or service-role keys.

---

## 1. One-sentence project summary

Classroom Voice Notes is a local-first Windows desktop application for teachers that captures spoken classroom notes locally, classifies them locally, keeps sensitive school data offline, and now needs a safe, audited way to send only approved non-sensitive `agent_task` payloads to an off-site AI agent via a Supabase broker.

---

## 2. Why this project exists

The original external-agent idea used Telegram as the communication layer between Classroom Voice Notes and off-site agents such as Hermes/OpenClaw. That design became too brittle because Telegram behaves like a chat system rather than a reliable task broker. It introduces problems around agent-to-agent routing, team chats, threading, unclear task state, and limited auditability.

The replacement design is a purpose-built broker:

```text
Classroom Voice Notes
  → local transcription
  → local LLM classification
  → hard-coded privacy gate
  → safe external task payload
  → local outbox
  → signed HTTPS POST
  → Supabase broker
  → off-site agent processes task later
```

The broker is intentionally submit-only at this stage. It can receive approved tasks, store them durably, and place them into a queue. It does not yet support claim/complete/fail, status polling, or VPS agent polling.

---

## 3. Core privacy principle

The system must assume classroom notes may contain sensitive school information.

The external broker must never receive:

- raw audio
- raw classroom transcripts
- student names
- parent contact information
- behaviour notes
- welfare notes
- medical details
- absence details
- local Obsidian vault paths
- Windows usernames or local file paths
- unreviewed LLM output

The only data that may leave the local machine is a deliberately generated, non-sensitive, safe external task brief.

The local LLM may suggest that a note is safe, but the hard-coded `PolicyGate` must make the final decision. The system should fail closed.

---

## 4. Current production state

Supabase Broker Milestone 1 has been promoted to production and passed testing.

### Production broker status

| Area | Current state |
|---|---|
| Production database migration | Applied |
| Edge Function | `cvn-submit-task` deployed and active |
| JWT verification | Off for `cvn-submit-task` |
| HTTP tests | 9/9 passed in production |
| Claim/complete/fail endpoints | Not built |
| VPS polling agent | Not connected |
| Classroom Voice Notes app | Not connected yet |
| Real classroom data | Not used |

### Applied production migrations

| Migration | Purpose |
|---|---|
| `001_cvn_broker_mvp.sql` | Creates core broker tables, event log, pgmq queue, and submit RPC |
| `002_pgmq_schema_grants.sql` | Grants production `service_role` access to resolve the `pgmq` schema |
| `003_cvn_submit_task_security_definer.sql` | Makes `cvn_submit_task` a tightly scoped `SECURITY DEFINER` function with explicit search path |

### Production row state after tests

Production contains fake diagnostic/test rows only.

| Object | Count after test completion |
|---|---:|
| `public.cvn_tasks` | 4 |
| `public.cvn_task_events` | 4 |
| `pgmq.q_cvn_tasks_queue` | 4 |

These rows are expected and should not be removed by disabling audit triggers. The event log is intentionally append-only.

---

## 5. Supabase broker architecture

### Main database objects

#### `public.cvn_tasks`

Stores durable broker task records.

Important fields include:

- `task_id`
- `created_at`
- `source_device_id`
- `target_agent`
- `status`
- `priority`
- `payload_json`
- `payload_hash`
- `privacy_classification`
- `policy_gate_version`
- `checks_passed`
- `idempotency_key`
- `nonce`
- `signed_at`
- `redactions_applied`
- retry/result/error fields reserved for later milestones

Important constraints:

- `privacy_classification` must be `non_sensitive`
- `task_id` must match the expected `CVN-YYYYMMDD-HHMMSS-XXXX` pattern
- `idempotency_key` is unique
- `(source_device_id, nonce)` is unique
- target agent must be one of the accepted values, currently `hermes`, `openclaw`, or `auto`

#### `public.cvn_task_events`

Append-only audit/event log.

Important properties:

- no update
- no delete
- foreign key to `cvn_tasks` uses `ON DELETE RESTRICT`
- used to record submitted events and later will record claimed/completed/failed events

#### `pgmq.q_cvn_tasks_queue`

Postgres queue used by Supabase Queues / pgmq.

The queue message stores only minimal queue data, not the full payload. The task payload lives in `cvn_tasks`.

---

## 6. Critical database execution model

The production fix that finally made the broker work was this:

```text
public.cvn_submit_task(...) runs as SECURITY DEFINER
search_path = public, pgmq, pg_temp
EXECUTE is limited to service_role and postgres
anon and authenticated do not have EXECUTE
```

Why this matters:

- The Edge Function uses the service role key internally.
- The Edge Function calls `public.cvn_submit_task(...)` via RPC.
- The RPC inserts into `cvn_tasks`, appends to `cvn_task_events`, and enqueues to pgmq.
- The protected pgmq write is encapsulated inside the broker RPC.
- The system does not grant broad direct queue-table write access to external roles.

Do not remove `SECURITY DEFINER` or the explicit `search_path` without a deliberate security review.

---

## 7. Edge Function: `cvn-submit-task`

### Endpoint

```text
https://<production-project-ref>.supabase.co/functions/v1/cvn-submit-task
```

### Required headers

```text
Authorization: Bearer <CVN_BEARER_TOKEN>
x-cvn-signature: <HMAC_SHA256_HEX_OF_RAW_JSON_BODY>
Content-Type: application/json
```

### Required function behaviour

The Edge Function must:

1. reject non-POST requests
2. check its required environment secrets are present
3. check bearer token using timing-safe comparison
4. read the raw body once
5. verify HMAC over the exact raw body
6. parse JSON only after HMAC verification
7. reject `signed_at` timestamps more than 5 minutes in the past or future
8. validate schema version `cvn.agent_task.v1`
9. require `source_device_id`
10. require `privacy.classification = non_sensitive`
11. call `cvn_submit_task(...)`
12. return `200` with `accepted: true`, `task_id`, `status_url`, and `msg_id` on success
13. return `409 duplicate_idempotency_key` or `409 duplicate_device_nonce` where appropriate

### Production test results

The production Edge Function passed these nine fake non-sensitive HTTP tests:

| Test | Expected result | Production result |
|---|---|---|
| Valid signed task | `200` | Passed |
| Wrong bearer token | `401 Unauthorized` | Passed |
| Tampered body | `401 Invalid signature` | Passed |
| Stale past `signed_at` | `401 Stale signed_at` | Passed |
| Future `signed_at` | `401 Stale signed_at` | Passed |
| Missing `task.instructions` | `400 schema_validation_failed` | Passed |
| Bad privacy classification | `400 schema_validation_failed` | Passed |
| Duplicate `idempotency_key` | `409 duplicate_idempotency_key` | Passed |
| Duplicate `(source_device_id, nonce)` | `409 duplicate_device_nonce` | Passed |

---

## 8. Secret and token hygiene

The production `CVN_HMAC_SECRET`, production `CVN_BEARER_TOKEN`, and Supabase personal access token have appeared in chat/logs during setup.

Before connecting the real Classroom Voice Notes app to production, rotate:

- production `CVN_HMAC_SECRET`
- production `CVN_BEARER_TOKEN`
- Supabase personal access token

Do not write secrets into:

- source files
- Git commits
- `settings.json`
- logs
- test output
- documentation

Classroom Voice Notes should store local copies of `CVN_HMAC_SECRET` and `CVN_BEARER_TOKEN` in Windows Credential Manager via Python `keyring`. The app config should reference secret names, not secret values.

---

## 9. What must not be done yet

Do not start Milestone 2 yet.

Do not build or deploy:

- `cvn-claim-task`
- `cvn-complete-task`
- `cvn-fail-task`
- `cvn-status`
- pg_cron reaper jobs
- VPS `watch_inbox.py` poller
- agent result callbacks
- Classroom Voice Notes result polling

Do not connect real classroom notes to the broker until the CVN-side safety work is complete and secrets are rotated.

Do not remove diagnostic/test rows by disabling append-only triggers.

---

## 10. Next coding work: Classroom Voice Notes application integration

The next development work is in the Classroom Voice Notes app repository.

### Branch

```bash
git checkout -b feature/external-agent-broker
```

### Goal

Add a safe local-to-Supabase-broker dispatch path that replaces the Telegram dependency for approved `agent_task` payloads.

The app should be able to submit fake non-sensitive tasks to the production broker after local safety gates pass. It should not yet implement result polling or claim/complete/fail behaviour.

---

## 11. Required CVN app-side work

### 11.1 Add `ExternalAgentDispatcher`

Add a new module:

```text
app/destinations/external_agent_dispatcher.py
```

Do not delete `telegram_dispatcher.py` yet. Keep the Telegram path until the new broker path is fully tested.

Responsibilities:

- build the final safe payload
- serialise JSON deterministically enough for signing
- compute HMAC-SHA256 hex signature over the raw JSON body
- send signed HTTPS POST to `cvn-submit-task`
- handle success and error responses
- update local note/outbox status
- log audit events locally

### 11.2 Add local outbox

Add a local SQLite outbox, for example:

```text
app/destinations/external_outbox.py
```

Suggested fields:

- `local_id`
- `task_id`
- `created_at`
- `endpoint_url`
- `payload_json`
- `payload_hash`
- `status`
- `attempt_count`
- `next_retry_at`
- `last_error`
- `sent_at`
- `remote_msg_id`
- `idempotency_key`
- `nonce`

Suggested statuses:

- `pending`
- `sending`
- `sent`
- `failed`
- `dead_letter`

Suggested retry pattern:

```text
3 seconds → 9 seconds → 27 seconds → 81 seconds → 243 seconds → hourly
```

Local expiry target: 7 days, then local dead-letter unless manually resent.

### 11.3 Add external agent config

Add an `external_agent` section to settings. It should be disabled by default.

```json
{
  "external_agent": {
    "enabled": false,
    "endpoint_url": "https://<production-project-ref>.supabase.co/functions/v1/cvn-submit-task",
    "hmac_secret_ref": "cvn_hmac_secret",
    "bearer_token_ref": "cvn_bearer_token",
    "target_agent_default": "hermes",
    "source_device_id": "<stable-local-device-id>"
  }
}
```

Secret values must not be stored here.

### 11.4 Add keyring secret lookup

Use Python `keyring` to read:

- `cvn_hmac_secret`
- `cvn_bearer_token`

If a secret is missing, the dispatcher must fail closed and not send.

### 11.5 Generate safe external task payloads

Do not send raw transcripts.

The local workflow should be:

```text
raw transcript
  → local classification
  → separate safe_external_task generation
  → hard-coded PolicyGate validation
  → local outbox
  → signed broker POST
```

The payload should match `cvn.agent_task.v1` and include:

- `schema_version`
- `task_id`
- `created_at`
- `source`
- `source_device_id`
- `target_agent`
- `privacy.classification`
- `privacy.policy_gate_version`
- `privacy.checks_passed`
- `task.title`
- `task.instructions`
- `task.priority`
- `redactions_applied`
- `signed_at`
- `nonce`
- `idempotency_key`

### 11.6 Harden `PolicyGate`

The current policy gate concept must become stricter before live use.

Required checks:

- category must be exactly `agent_task`
- sensitivity must be exactly `non_sensitive`
- safe external task must exist
- student registry must load successfully
- transcript and safe task must be scanned for student names
- forbidden keyword scan must pass
- no audio attachment
- no local file paths
- no raw transcript in payload
- no parent contact details
- no behaviour/welfare/medical/absence content
- payload size under limit
- `source_device_id` present
- `target_agent` is allowlisted
- endpoint domain is allowlisted

If any check fails, external dispatch is blocked and logged locally.

---

## 12. Suggested safe payload example

```json
{
  "schema_version": "cvn.agent_task.v1",
  "task_id": "CVN-20260708-124537-P1B2",
  "created_at": "2026-07-08T12:45:37+00:00",
  "source": "classroom_voice_notes",
  "source_device_id": "cvn-douglas-classroom-pc-001",
  "target_agent": "hermes",
  "privacy": {
    "classification": "non_sensitive",
    "policy_gate_version": "1.0.0",
    "checks_passed": [
      "category_agent_task",
      "safe_external_task_generated",
      "no_student_registry_match",
      "no_forbidden_terms",
      "no_audio_attached",
      "no_local_file_path",
      "payload_size_ok"
    ]
  },
  "task": {
    "title": "Update local save command wording",
    "instructions": "Change the local spoken save command from 'save' to 'thanks Joshua'. Update tests and documentation. Do not change any cloud dispatch settings.",
    "priority": "normal"
  },
  "redactions_applied": [],
  "signed_at": "2026-07-08T12:45:37+00:00",
  "nonce": "example-nonce-replace-with-random",
  "idempotency_key": "example-idempotency-key-replace-with-random"
}
```

This is an example only. Real nonce and idempotency values must be random and unique.

---

## 13. Required tests for the CVN app branch

Add automated tests for:

- valid fake safe task builds a correct payload
- HMAC signature is computed over the exact raw JSON body
- missing HMAC secret blocks dispatch
- missing bearer token blocks dispatch
- external dispatch disabled blocks dispatch
- sensitive classification blocks dispatch
- non-agent-task category blocks dispatch
- student registry load failure blocks dispatch
- student name match blocks dispatch
- forbidden keyword match blocks dispatch
- local file path match blocks dispatch
- raw transcript is not present in outgoing payload
- outbox records pending task before send
- outbox marks sent after `200 accepted`
- outbox records `409 duplicate_idempotency_key` safely
- network failure leaves task retryable
- repeated failures move task to local dead-letter

Use fake non-sensitive payloads only.

---

## 14. Milestone 2, later

Only after the CVN app can safely submit tasks should broker Milestone 2 begin.

Milestone 2 will likely add:

- `cvn-claim-task`
- `cvn-complete-task`
- `cvn-fail-task`
- `cvn-status`
- stale-claim reaper
- retry/dead-letter handling
- VPS polling worker
- agent result summaries
- optional CVN status polling

Do not assume these endpoints exist in the current CVN app integration.

---

## 15. Agent operating rules

Any coding agent working on this project must follow these rules:

1. Do not use real classroom data.
2. Do not send real student information externally.
3. Do not commit secrets.
4. Do not store secrets in `settings.json`.
5. Do not delete or disable append-only audit protections.
6. Do not start Milestone 2 unless explicitly instructed.
7. Do not connect the live CVN app to production until the app-side safety checks are implemented and reviewed.
8. Do not bypass the local `PolicyGate`.
9. Do not send raw transcript text externally.
10. Do not change production broker migrations without a new migration file.
11. Stop immediately if tests fail in production.
12. Use fake non-sensitive test payloads only.

---

## 16. Immediate next action for the coding agent

Start the Classroom Voice Notes app-side branch:

```bash
git checkout -b feature/external-agent-broker
```

Then implement, in order:

1. config model for `external_agent`
2. keyring secret lookup
3. safe payload builder
4. HMAC signer
5. local outbox
6. `ExternalAgentDispatcher`
7. hardened `PolicyGate`
8. tests
9. one fake non-sensitive end-to-end submit test against the production broker, only after secrets are rotated and the dispatcher remains disabled by default

This is now the correct place to continue work.
