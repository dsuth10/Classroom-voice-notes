# Outbound Sharing Remediation and Delivery Plan

**Audience:** Junior engineer, with senior review for security and database work  
**Repository baseline:** `main` at `7ffc17ecb6144807fa09ad9c03e3723319374b9b`  
**Feature area:** Settings-driven sharing to OpenClaw or Hermes, human review, trusted automatic release, and spreadsheet/record export  
**Current release status:** **Do not enable outside synthetic staging data**

## 1. Purpose

The merged feature establishes most of the pieces needed for outbound sharing, but those pieces are not yet connected into a safe, complete delivery path. This plan turns the current implementation into a production-quality feature that:

- keeps the existing automatic filtering option;
- allows a user to choose a human-in-the-loop review mode;
- optionally allows trusted automatic release for users who knowingly accept the risk;
- sends the exact content that was assessed and approved;
- stores record-only items for spreadsheet consumption without accidentally executing them as agent tasks;
- supports OpenClaw cleanly;
- does not claim Hermes support until a real Hermes integration exists;
- fails closed when configuration, validation, approval, or delivery is incomplete.

This document is intentionally split into small pull requests. Complete and review them in order. Do not combine all of the work into one large change.

## 2. Release blockers found in the merged implementation

Treat the following as stop-ship defects:

1. **The settings screen and routing service use different settings.** The UI writes `external_agent.enabled`, while the new routing service reads `external_agent.sharing_mode`. A user can therefore disable the old checkbox while outbound routing remains active, or enable the checkbox while outbound routing remains off.
2. **The Supabase submission function can be called without the Edge Function security checks.** Migration `008_cvn_outbound_items.sql` grants direct execution to `authenticated`, and PostgreSQL functions are executable by `PUBLIC` unless access is explicitly revoked.
3. **“Approve & Send” does not send.** The review dialog changes the local status to `approved`, but it does not build a v2 payload or enqueue it for delivery. Trusted mode reports `trusted_auto_queued` without queueing anything.
4. **The server trusts the client’s content hash.** It does not independently recompute the hash of the exact outgoing content or compare that value with the approved hash.
5. **The policy gate does not inspect all v2 content fields.** A record-only item may contain sensitive transcript or structured data that is not present in the legacy task fields being checked.
6. **The new Supabase queue has no complete consumer lifecycle.** Items are inserted into `q_cvn_outbound_queue`, but there is no matching claim/complete/fail workflow and no running worker that consumes the queue.
7. **Migration 009 uses conflicting dollar-quote delimiters.** Its `DO $$ ... $$` block contains another `$$ ... $$` string and is expected to fail when applied.
8. **The full test suite hangs and the secret scan fails.** A UI test opens a blocking message box, and Gitleaks identifies the high-entropy test value in `tests/unit/test_outbound_payload_builder.py` as a generic API key.

Do not deploy migrations 008 or 009, deploy `cvn-submit-outbound-item`, or enable `review_all`/`trusted_auto` until the relevant sections below are complete.

## 3. Target behaviour

### 3.1 User-facing modes

Use one authoritative setting: `external_agent.sharing_mode`.

| Mode | User-facing label | Behaviour |
|---|---|---|
| `off` | Keep everything on this device | Never create or send an outbound item. |
| `safe_auto` | Automatically send only items that pass the safety filter | Preserve the existing v1 agent-task flow. Anything that does not pass stays local. |
| `review_all` | Review every item before sending | Create a v2 review item. Nothing leaves the device until the user approves the exact final content. |
| `trusted_auto` | Automatically send, pausing on high risk | Create and assess a v2 item, then enqueue it automatically unless a high-risk finding requires review. Display a prominent warning before this mode can be saved. |

The old `external_agent.enabled` value must not remain a second source of truth. After its one-time migration, either remove its runtime use or expose a compatibility helper that derives “enabled” from `sharing_mode != "off"`.

### 3.2 Item types

| Item kind | Meaning | Allowed destination behaviour |
|---|---|---|
| `record_only` | Store a structured capture for a spreadsheet/database consumer | Persist/export the record. Never execute instructions. |
| `agent_task` | Send an explicitly defined task to an agent | Execute only after the correct release policy and agent adapter validation. |

Never convert `record_only` content into agent instructions. Keep the record consumer and task adapters as separate code paths.

### 3.3 Required delivery sequence

For review mode, the correct sequence is:

1. Create a local draft.
2. Assess every field that could leave the device.
3. Let the user edit the draft.
4. Reassess the edited draft.
5. Show a final, read-only preview and the latest findings.
6. Record approval of the canonical hash of that exact preview.
7. Build the v2 payload using the same canonical content.
8. Enqueue the payload locally.
9. Deliver it through the authenticated Edge Function.
10. Have the server recompute and validate the content hash.
11. Claim and process it using the correct record or agent consumer.
12. Reconcile final state back to the local review record and note frontmatter.

If any step fails, preserve an actionable local state and never silently mark the item as sent.

## 4. Recommended pull-request sequence

## PR 1 — Restore a reliable quality baseline

### Goal

Make `main` deterministic so later changes can rely on CI.

### Files

- `tests/unit/test_outbound_review_dialog.py`
- `tests/unit/test_outbound_payload_builder.py`
- `.gitignore`
- `run_debug.log`
- optionally `crash.log` and other tracked runtime logs
- `Ideas/Phase3.md`

### Tasks

1. Fix the blocking UI test.
   - The test currently calls `_on_save_edits_clicked()`, which opens `QMessageBox.information()` and waits forever.
   - Patch the message-box call in the test, or change the UI to emit a non-blocking status message that can be asserted.
   - Add an assertion for both the saved draft and the user-visible confirmation.
2. Replace the 64-character high-entropy value named `secret` in `test_outbound_payload_builder.py` with an obvious low-entropy test fixture such as `"test-hmac-secret-not-for-production"`.
   - Prefer changing the fixture over adding a broad Gitleaks allowlist.
3. Remove committed runtime logs from version control and add focused ignore entries such as `run_debug.log`, `crash.log`, and `*.log` if the repository has no log files that are intentionally maintained.
   - Do not delete a useful source fixture merely because it has a `.log` extension; check tracked files first.
4. Replace absolute `C:\...` documentation links in `Ideas/Phase3.md` with repository-relative links.
5. Run formatting/lint cleanup only on files touched by the feature. Avoid a repository-wide whitespace-only change in the same PR.

### Tests and checks

```powershell
uv run --frozen ruff check app tests scripts run.py
uv run --frozen mypy app
uv run --frozen pytest tests -p no:cacheprovider
```

Also confirm the GitHub secret-scanning job passes.

### Definition of done

- The full test command exits without user interaction.
- Ruff and mypy pass.
- Gitleaks reports no secret in test fixtures.
- Runtime logs and local machine paths are not committed.

## PR 2 — Make sharing mode the single source of truth

### Goal

Ensure the displayed setting, saved setting, startup behaviour, capture routing, Telegram behaviour, and outbox worker all agree.

### Files

- `app/config/settings.py`
- `app/ui/main_window.py`
- `app/controller.py`
- `app/transcription/worker.py`
- `app/destinations/external_agent_dispatcher.py`
- related settings, controller, window, worker, and dispatcher tests

### Tasks

1. Add a sharing-mode selector to the settings panel with the four labels in section 3.1. Save its stable internal value, not its display text.
2. Add controls for:
   - include full transcript, default off;
   - default item kind, default `record_only`;
   - target agent, default only to an actually supported adapter;
   - pause trusted mode on high-risk findings, default on;
   - a button showing the pending-review count and opening the review queue.
3. Remove the old broker-enabled checkbox, or make it a derived presentation of the selected mode. Do not save `external_agent.enabled` from the UI.
4. Keep the existing migration in `SettingsManager`, but make it one-way and test it:
   - legacy `enabled: true`, no `sharing_mode` → `safe_auto`;
   - legacy `enabled: false`, no `sharing_mode` → `off`;
   - an existing valid `sharing_mode` always wins;
   - an invalid mode fails closed to `off`.
5. Add a helper such as `external_sharing_enabled()` returning `external_sharing_mode() != "off"`. Replace every runtime read of `external_agent.enabled` in the controller, transcription worker, and dispatcher with either this helper or a mode-specific branch.
6. Decide whether Telegram is part of this setting. The safest default is that all external dispatch is disabled when sharing mode is `off`. Capture this decision in tests.
7. When a user chooses `trusted_auto`, show a confirmation explaining that data may leave the device without per-item review. If they cancel, restore the previous mode.
8. Generate and persist a stable `source_device_id` when none exists. Do not depend on `get(..., default)` if the stored key can be an empty string.
9. Wire the review dialog into the main window; it currently exists only as an isolated class/test target.

### Tests

Add table-driven tests for all four modes across:

- settings load/save and migration;
- capture routing;
- outbox timer startup;
- Telegram/external dispatch guards;
- settings UI load/save;
- trusted-mode confirmation cancellation;
- pending-review button and count.

### Definition of done

- Searching for `external_agent.enabled` finds only migration/legacy-test code, not runtime decisions.
- Selecting `off` prevents all outbound routing after application restart.
- Each UI selection persists and is reflected by the routing service.
- The review queue is reachable from the normal application UI.

## PR 3 — Close the Supabase authorization bypass and repair migrations

### Goal

Make the Edge Function the only normal submission path and ensure migrations apply cleanly from an empty database.

### Files

- `supabase/migrations/008_cvn_outbound_items.sql`
- `supabase/migrations/009_cvn_outbound_reaper.sql`
- new forward-fix migration if 008/009 have already been applied anywhere
- Supabase integration tests

### Tasks

1. Restrict the security-definer submission RPC.

```sql
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item(...) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item(...) FROM anon;
REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item(...) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item(...) TO service_role;
```

Use the function’s complete argument signature in the migration. Also set a safe `search_path` on every `SECURITY DEFINER` function and schema-qualify referenced objects.

2. If a shared/staging database may already contain migration 008, do not rewrite history alone. Add a new forward migration that revokes the old grants. The edited base migration may still be useful for fresh installations, but the forward migration is what fixes existing environments.
3. Repair the nested dollar quoting in migration 009. For example:

```sql
DO $block$
BEGIN
    PERFORM cron.schedule(
        'cvn-outbound-reaper',
        '*/5 * * * *',
        $job$SELECT public.cvn_reap_outbound_items();$job$
    );
END
$block$;
```

4. Make cron registration idempotent. Unschedule or update a job with the same name before creating it, depending on the supported `pg_cron` version.
5. Define what happens to a PGMQ message when its corresponding row expires or is deleted. The reaper must not leave an orphaned message that can later be processed.
6. Apply timestamp checks inside the database as defence in depth. Reject timestamps that are too old **or too far in the future**, matching the absolute-skew rule used by the Edge authentication layer.
7. Add database constraints for enums and state where practical: schema version, item kind, release basis, target agent, and lifecycle status.

### Security tests

Prove all of the following:

- `anon` cannot execute the RPC directly;
- `authenticated` cannot execute it directly;
- `PUBLIC` has no effective execute grant;
- `service_role` can execute it;
- an Edge request with a bad signature is rejected;
- stale and future timestamps are rejected;
- a repeated idempotency key returns the existing item rather than duplicating it;
- migrations 001 through 009 plus any forward fixes apply from an empty database.

### Definition of done

- Direct client RPC calls cannot bypass bearer, HMAC, nonce, or timestamp verification.
- All migrations apply cleanly and can be reapplied in the expected local reset workflow.
- The reaper does not create duplicate cron jobs or orphan queue messages.

## PR 4 — Enforce the local review state machine

### Goal

Prevent edits or approvals from producing impossible states, and preserve the relationship between the approved content and queued payload.

### Files

- `app/destinations/outbound_review_store.py`
- `app/ui/outbound_review_dialog.py`
- `tests/unit/test_outbound_review_store.py`
- `tests/unit/test_outbound_review_dialog.py`

### State model

Use explicit transitions. A suitable minimum is:

| Current state | Allowed next states | Trigger |
|---|---|---|
| `awaiting_review` | `awaiting_review`, `approved_pending_enqueue`, `rejected`, `expired` | edit/reassess, approve, reject, expiry |
| `approved_pending_enqueue` | `queued`, `enqueue_failed` | local enqueue success/failure |
| `enqueue_failed` | `approved_pending_enqueue`, `rejected` | retry or cancel |
| `queued` | `sent`, `delivery_failed` | worker result |
| `delivery_failed` | `queued`, `rejected` | retry or cancel |
| `sent` | none | terminal |
| `rejected` | none | terminal |
| `expired` | none | terminal |

If product requirements need reopening a rejected item, create a new item with a new ID rather than mutating the old audit record.

### Tasks

1. Add a checked transition helper in `OutboundReviewStore`. Each update must include the expected current state in its SQL `WHERE` clause and verify that exactly one row changed.
2. Make `approve()` legal only from `awaiting_review`. Make edits legal only from `awaiting_review`. Disallow rejecting or editing `queued` and `sent` records.
3. Update `update_draft()` to persist `item_kind` and `target_agent` columns as well as `draft_json` and `content_hash`. The current code calculates the new values but leaves the columns stale.
4. Store `approved_content_hash` separately when approval occurs. Do not rely on a mutable general-purpose `content_hash` field to represent both draft and approval.
5. Record useful timestamps and failure information: `approved_at`, `queued_at`, `sent_at`, `last_error`, and retry count.
6. Add database `CHECK` constraints for known statuses on newly created databases. For existing SQLite databases, implement an explicit versioned migration because SQLite cannot add all constraints in place.
7. Make audit events describe the real transition and item ID, without including sensitive content.
8. Replace misleading action labels. Never return or display “queued” until a durable outbox row exists.

### Transaction note

The review store and external outbox currently use separate SQLite databases, so approving and enqueueing cannot be one normal SQLite transaction. Use the recoverable `approved_pending_enqueue` state:

1. Save approval and its content hash.
2. Attempt idempotent outbox insertion using `item_id` as the business key.
3. Save the returned outbox ID and move to `queued`.
4. On startup and periodically, reconcile `approved_pending_enqueue` and `enqueue_failed` items by checking for an existing outbox row before inserting.

Do not mark an item `queued` first and hope the enqueue succeeds later.

### Tests

- Every allowed transition succeeds.
- Every disallowed transition leaves the row unchanged.
- Editing changes the canonical hash and clears prior approval.
- Editing item kind or target agent updates both columns and JSON.
- A simulated crash after approval but before enqueue is recovered idempotently.
- Repeating enqueue does not create two outbox rows.

### Definition of done

- Review records cannot skip required lifecycle states.
- The exact approved hash is immutable and auditable.
- A crash cannot lose an approved item or duplicate its outbound delivery.

## PR 5 — Assess the exact outgoing v2 content

### Goal

Run privacy policy over everything that will leave the device, both before review and after edits.

### Files

- `app/ollama_router/policy_gate.py`
- `app/privacy/outbound_assessment.py`
- `app/destinations/outbound_routing_service.py`
- `app/ui/outbound_review_dialog.py`
- policy and routing tests

### Tasks

1. Add one v2 assessment entry point that accepts the proposed `item_kind`, `target_agent`, `content`, and optional `task`.
2. Build the text to inspect from the exact outgoing fields, including:
   - content title and summary;
   - transcript when included;
   - tags;
   - category and structured/category fields;
   - task title and instructions for `agent_task`;
   - any other free-text field added later.
3. Run all relevant rules over that combined content: student names, contact information, medical/safeguarding terms, forbidden terms, local file paths, audio paths/extensions, credential-like content, and any existing policy checks.
4. Preserve field-level findings where possible, for example `content.transcript: email_address`, so the review UI can explain where the issue is.
5. Fix the classifier field mismatch. The classifier currently produces `category_fields`, while the routing service reads `structured_fields`. Choose one canonical payload name and add a compatibility mapping if old records may exist.
6. After “Save edits”, immediately reassess the changed draft and update the displayed risk/findings. Do not reuse the assessment captured before the edit.
7. Before approval, display a final read-only preview generated from the same in-memory object that will be hashed and enqueued.
8. Make “Apply suggested redactions” actually change the relevant fields, then reassess. If automatic application cannot be made reliable, rename the button to “View suggested redactions”.
9. In trusted mode, keep the default “pause on high risk” enabled. A malformed assessment or assessment exception must also pause/fail closed.
10. Populate `privacy.checks_passed` for automatic-policy releases and validate the required checks server-side.

### Tests

Create parameterized cases showing that sensitive data is caught in each individual field, especially a `record_only` transcript containing:

- a student name;
- an email address;
- a phone number;
- a medical/safeguarding term;
- a Windows or Unix local path;
- an audio filename;
- a credential-like string.

Also test that editing a safe item into an unsafe item changes the risk before approval, and that an assessment exception never releases automatically.

### Definition of done

- The assessment is calculated from the exact object being approved.
- No v2 free-text field bypasses policy checks.
- Edited content cannot retain an approval or stale low-risk result.

## PR 6 — Connect approval and trusted mode to the durable outbox

### Goal

Make the user-visible actions truthful: approved items are built, enqueued, delivered, and reconciled.

### Files

- new `app/destinations/outbound_submission_service.py` (recommended)
- `app/destinations/outbound_payload_builder.py`
- `app/destinations/outbound_review_store.py`
- `app/destinations/external_outbox.py`
- `app/destinations/outbox_worker.py`
- `app/destinations/outbound_routing_service.py`
- `app/ui/outbound_review_dialog.py`
- related unit/integration tests

### Design

Create a single `OutboundSubmissionService` used by both manual approval and trusted automatic release. It should:

1. load the review row;
2. verify it is in an allowed state;
3. deserialize and validate the draft;
4. recompute the canonical content hash;
5. compare it with `approved_content_hash`;
6. build `cvn.outbound_item.v2`;
7. enqueue it idempotently in `ExternalOutbox`;
8. update the review row to `queued` only after enqueue succeeds;
9. update note frontmatter;
10. return a typed result that distinguishes queued, already queued, validation failure, and enqueue failure.

### Tasks

1. Change the review dialog’s “Approve & Send” handler to:
   - save/reassess any pending edits;
   - show the final preview;
   - obtain explicit confirmation;
   - approve the exact hash;
   - call the submission service;
   - display `Queued for delivery` only after durable enqueue.
2. Change trusted mode to use the same service. Do not duplicate payload construction in `OutboundRoutingService`.
3. Extend the local outbox schema only as needed to store v2 metadata such as `schema_version`, `item_id`, `item_kind`, `review_id`, `target_agent`, `content_hash`, and release basis. Add a migration for existing outbox databases.
4. Make `item_id` or idempotency key unique in the outbox.
5. Teach the outbox worker to select the correct submission endpoint based on schema version. Preserve the existing v1 endpoint for `safe_auto` tasks and use `cvn-submit-outbound-item` for v2.
6. Preserve the original capture time. `recorded_at` and `duration_seconds` are currently accepted by the routing service and then discarded. Include them in the content/schema and use `recorded_at` as the spreadsheet’s capture timestamp.
7. Return the actual dispatch result in safe-auto mode. If `ExternalAgentDispatcher.dispatch()` fails or declines, do not return `safe_auto_dispatched`.
8. On successful broker submission, record remote ID/status. On failure, keep the local row retryable and show the last error without exposing secrets.
9. Reconcile note frontmatter through each meaningful state: `awaiting_review`, `approved_pending_enqueue`, `queued`, `sent`, `delivery_failed`, `rejected`, or `expired`.

### Tests

- Manual approval creates exactly one v2 outbox row.
- Trusted release uses the same payload and enqueue path.
- A hash mismatch blocks enqueue.
- An enqueue exception produces a recoverable state.
- Retrying after an ambiguous result is idempotent.
- A v1 task still uses the existing endpoint and behaviour.
- A v2 item uses the new endpoint.
- UI wording matches the durable state.

### Definition of done

- `build_outbound_payload_v2()` is used by application code, not only tests.
- `mark_queued()` and `mark_sent()` are driven by real delivery events.
- No method reports a successful dispatch or queue operation that did not happen.

## PR 7 — Validate approval and payload integrity on the server

### Goal

Do not trust client-declared hashes, release basis, schema, or field sizes.

### Files

- `supabase/functions/cvn-submit-outbound-item/index.ts`
- a shared TypeScript canonicalization/validation module under `supabase/functions/_shared/`
- `supabase/migrations/008_cvn_outbound_items.sql` or a forward-fix migration
- Edge and integration tests

### Canonical hash specification

The content hash is the lowercase SHA-256 hex digest of UTF-8 JSON for this object:

```json
{
  "item_kind": "record_only",
  "target_agent": "openclaw",
  "content": {},
  "task": {}
}
```

The JSON must use these rules in Python and TypeScript:

- recursively sort object keys;
- preserve array order;
- encode without insignificant whitespace;
- represent an absent target as an empty string;
- represent an absent task as an empty object;
- reject unsupported JSON values rather than coercing them.

Add shared test vectors containing nested objects, Unicode, arrays, an absent task, and an agent task. Python and TypeScript must produce identical canonical JSON and digests.

### Server validation order

1. Enforce an explicit request-body size limit before parsing.
2. Verify bearer/HMAC authentication, signed timestamp, nonce, and replay protection.
3. Validate all required fields, enum values, string lengths, collection sizes, and nesting depth.
4. Recompute the canonical content hash from `item_kind`, `target_agent`, `content`, and `task`.
5. Reject if recomputed hash differs from top-level `content_hash`.
6. For `human_approval`, require approval metadata and reject if `approved_content_hash` differs from the recomputed hash.
7. For `automatic_policy`, reject missing/unknown required policy checks and high-risk content according to the agreed contract.
8. For `trusted_mode`, require that the client/account is explicitly allowed to use trusted mode; do not accept a release basis merely because the request claims it.
9. Call the service-role-only RPC with server-derived values.

The database function should repeat critical enum, timestamp, state, and hash-shape checks as defence in depth. It should not accept arbitrary caller-provided states.

### Minimum schema limits

Agree exact values with the maintainer, then encode and test them. At minimum limit:

- total body bytes;
- title, summary, transcript, task title, and instructions length;
- number and length of tags;
- findings and checks count;
- structured-field keys, values, depth, and total serialized size;
- item ID, device ID, target agent, nonce, and idempotency-key length.

### Tests

- Tampering with content after approval is rejected.
- Tampering only with `content_hash` is rejected.
- An incorrect `approved_content_hash` is rejected.
- Missing approval metadata is rejected for human approval.
- Unknown release basis, item kind, schema, status, or target is rejected.
- Oversized/deep content is rejected before database insertion.
- Python and TypeScript canonicalization vectors match.
- Replay, stale timestamp, future timestamp, and duplicate idempotency cases behave as specified.

### Definition of done

- The server independently proves that the submitted content is the content approved.
- A client cannot self-authorize a stronger release mode.
- Malformed or oversized payloads fail before entering the queue.

## PR 8 — Implement the remote v2 queue lifecycle and consumers

### Goal

Give `q_cvn_outbound_queue` a complete, observable claim/complete/fail lifecycle and process record-only items separately from agent tasks.

### Files

- new or extended Supabase migrations/RPCs
- new Edge Functions or version-aware claim/complete/fail/status functions
- `app/destinations/record_consumer.py`
- `app/destinations/openclaw_adapter.py`
- worker scripts/services and integration tests

### Tasks

1. Define remote states such as `queued`, `claimed`, `completed`, `failed_retryable`, `dead_letter`, and `expired`.
2. Implement service-role-only RPCs for:
   - claim with visibility timeout and worker identity;
   - complete with result metadata;
   - fail with retry/dead-letter decision;
   - status lookup by item ID/idempotency key.
3. Put authenticated Edge Functions in front of these RPCs. Follow the established v1 worker-identity and HMAC patterns where possible.
4. Route by `item_kind` after claim:
   - `record_only` → record/spreadsheet consumer;
   - `agent_task` → explicitly selected supported agent adapter.
5. Make claim atomic so two workers cannot process the same visible message.
6. Use a visibility timeout and bounded retries. A crashed worker must not permanently strand an item.
7. Make completion idempotent. Repeated completion after a timeout must not append a second spreadsheet row or run a task twice.
8. Store attempt count, worker ID, claimed time, completion time, last error code, and final result reference for operational diagnosis.
9. Add a reconciliation path so the desktop can turn a broker-terminal result into local `sent` or `delivery_failed` state.
10. Decide who hosts the worker and how it is monitored before enabling staging. A queue without a deployed consumer is not a complete feature.

### Agent support

- Extend `OpenClawAdapter` deliberately for v2 `agent_task` payloads, or transform only the validated task portion into its supported v1 input at a clearly tested boundary.
- Do not register the current Hermes placeholder as runnable. Remove Hermes from selectable targets or display it as unavailable until a real adapter, endpoint contract, and tests exist.
- The server must reject an unsupported target instead of claiming an item and permanently failing it later.

### Tests

- Two concurrent claim attempts yield one owner.
- An expired visibility timeout permits safe retry.
- A repeated completion is idempotent.
- `record_only` never invokes an agent adapter.
- `agent_task` never enters the spreadsheet consumer by accident.
- Unsupported Hermes selection is rejected before queueing.
- Retry exhaustion creates a visible dead-letter record.

### Definition of done

- Every accepted v2 item has a real consumer path.
- Operators can identify queued, stuck, failed, and completed items.
- Duplicate delivery cannot duplicate a task execution or spreadsheet row.

## PR 9 — Harden spreadsheet/record export

### Goal

Produce complete, safe, idempotent records that agents and people can consume.

### Files

- `app/destinations/record_consumer.py`
- record-consumer unit and integration tests
- schema/documentation for the chosen spreadsheet destination

### Tasks

1. Agree the export columns before coding. Include at least:
   - item ID and idempotency key;
   - recorded/captured time and received time;
   - source device;
   - title, summary, category, tags;
   - structured/category fields;
   - transcript only when the user explicitly included it;
   - automatic classification, risk, release basis, and approval time;
   - processing status and result reference.
2. The current CSV consumer omits transcript. Include it only from the v2 content field; never recover it from local files on the consumer machine.
3. Prevent spreadsheet formula injection. Before writing text to CSV/spreadsheet cells, neutralize values beginning with `=`, `+`, `-`, or `@` according to the destination’s documented safe-import approach.
4. Replace scan-then-append idempotency with an atomic mechanism. Good options are:
   - a database table with a unique item ID that drives export;
   - an SQLite sidecar index with a unique constraint and transaction;
   - an API destination that supports an idempotency/unique key.
5. Use file locking or a single-writer worker if CSV remains the output. `csv.writer` alone does not prevent concurrent row corruption.
6. Write UTF-8 consistently and test commas, quotes, newlines, Unicode, and long transcript fields.
7. Define retention and access controls for the exported file. Trusted mode does not remove the need to protect the resulting spreadsheet.
8. Never log full outbound content, transcript, HMAC secret, bearer token, or local vault path.

### Tests

- Formula-like values are rendered as text, not formulas.
- Concurrent/repeated delivery creates one intact row.
- Multiline Unicode transcript round-trips correctly.
- Transcript exclusion is respected.
- Capture time is distinct from approval/receive time.
- Sensitive content is absent from application logs and error text.

### Definition of done

- The exported record is complete enough for the intended agent workflow.
- Duplicate messages cannot create duplicate rows.
- Opening the output in common spreadsheet software cannot execute injected formulas.

## PR 10 — End-to-end staging, documentation, and controlled rollout

### Goal

Prove the complete system with synthetic data and introduce the riskier modes gradually.

### Documentation tasks

Update the README and operational docs with:

- what each sharing mode does;
- what data leaves the device;
- how full transcript inclusion changes exposure;
- the difference between record-only and agent-task items;
- supported/unsupported agents;
- how to review, retry, reject, and inspect failed items;
- key rotation and secret storage;
- retention and deletion behaviour locally, in Supabase, and in the spreadsheet;
- how to disable sharing immediately;
- how to inspect the audit trail without exposing content.

### End-to-end scenarios

Use synthetic classroom-like data only. Test at least:

1. `off`: capture is local and produces no review/outbox/remote row.
2. `safe_auto`, safe agent task: existing v1 flow succeeds.
3. `safe_auto`, unsafe task: remains local.
4. `review_all`, record-only: review → edit → reassess → approve → queue → server → record consumer → local reconciliation.
5. `review_all`, agent task: same lifecycle through OpenClaw.
6. Reject from review: nothing enters the outbox.
7. Edit after assessment: approval is reset and risk recalculated.
8. Trusted mode, low risk: automatic release and delivery.
9. Trusted mode, high risk: pauses for review.
10. Network outage: local retry without duplicate remote item.
11. Worker crash after claim: item becomes visible and is processed once.
12. Tampered body/hash/approval: rejected by Edge/server.
13. Unsupported target: rejected before delivery.
14. Application restart in each non-terminal state: recovery is correct.

### Rollout order

1. Deploy backward-compatible database/Edge security changes with feature access still off.
2. Deploy and monitor the v2 consumer lifecycle.
3. Release the desktop client with default mode `off`.
4. Enable `record_only` + `review_all` for internal synthetic staging.
5. Run the full staging checklist and inspect audit/error data.
6. Enable OpenClaw `agent_task` + `review_all` for a small test group.
7. Enable `trusted_auto` only after explicit product/security sign-off and successful review-mode operation.
8. Enable Hermes only after its real adapter has its own acceptance test.

Do not use real student names, transcripts, medical information, safeguarding information, credentials, or production classroom data during staging.

### Operational acceptance criteria

- Alerts exist for growing queue depth, old claimed items, repeated failures, dead letters, and Edge authentication failures.
- Operators can correlate a local item ID with the broker and consumer result without searching message content.
- Secrets can be rotated without data loss.
- Disabling sharing stops new submissions immediately while preserving already queued records for an explicit operator decision.
- Recovery and rollback procedures are documented and rehearsed.

## 5. Cross-cutting implementation rules

### Fail closed

Treat an invalid mode, unknown schema, unsupported agent, missing approval, hash mismatch, assessment exception, malformed payload, unavailable key, or unavailable endpoint as “do not send”. Record a concise error and keep the item recoverable where appropriate.

### Idempotency

Use `item_id` as the stable business identity from capture through export. Transport attempts may refresh `signed_at`, nonce, and HMAC signature, but they must retain the same item ID, content hash, and idempotency identity. Put unique constraints at the local outbox, broker table, and final record store.

### Logging and audit

Log IDs, state transitions, rule codes, timestamps, attempt counts, and result codes. Do not log transcript/content, tokens, secrets, signatures, or full local paths. Audit records should be useful without becoming another sensitive-data store.

### Schema evolution

Do not silently reinterpret existing payload fields. Version local SQLite schemas and remote payload contracts. For each migration, test both a fresh database and an upgrade from the immediately previous schema.

### User language

Prefer clear labels such as “Keep on this device”, “Review before sending”, and “Queued for delivery”. Avoid telling the user an item was “sent” when it is only locally queued or accepted by the broker.

## 6. Suggested test structure

Add or extend the following groups:

- `tests/unit/test_settings.py`: mode migration, validation, stable device ID.
- `tests/unit/test_main_window.py`: controls, trusted warning, review queue entry point.
- `tests/unit/test_outbound_routing_service.py`: complete mode/category/risk matrix.
- `tests/unit/test_policy_gate_hardened.py`: every v2 field and unsafe-data class.
- `tests/unit/test_outbound_review_store.py`: state transitions and migrations.
- `tests/unit/test_outbound_review_dialog.py`: edit, reassess, preview, approve, reject without blocking dialogs.
- `tests/unit/test_outbound_payload_builder.py`: canonical hash vectors and release-basis metadata.
- new `tests/unit/test_outbound_submission_service.py`: hash verification and idempotent enqueue.
- `tests/unit/test_external_outbox.py` and `test_outbox_worker.py`: v1/v2 endpoint routing and recovery.
- `tests/unit/test_record_consumer.py`: schema completeness, concurrency, idempotency, and formula injection.
- Supabase integration tests: grants, migrations, authentication, validation, claims, retries, and completion.
- one opt-in synthetic staging test for the complete v2 path.

Every bug fixed in this plan needs a regression test that fails against baseline commit `7ffc17e` and passes with the fix.

## 7. Pull-request checklist

Use this checklist on every PR:

- [ ] The PR addresses one named section of this plan.
- [ ] Security-sensitive decisions are called out in the description.
- [ ] Database changes include upgrade and fresh-install coverage.
- [ ] Existing local data is preserved or a migration/backup path is documented.
- [ ] New states and error cases are visible to the user or operator.
- [ ] Logs contain no outbound content or secrets.
- [ ] Unit and relevant integration tests pass.
- [ ] Ruff and mypy pass.
- [ ] Full tests run without prompts or hangs.
- [ ] No real classroom data is used in fixtures, screenshots, or staging.
- [ ] User-facing documentation is updated when behaviour changes.

## 8. Final definition of done

The application is “up to scratch” for this feature only when all of the following are true:

- one persisted sharing mode controls all outbound behaviour;
- the default remains off and trusted mode requires explicit informed consent;
- the review queue is available from the main UI;
- all outgoing v2 fields are assessed, and edits force reassessment;
- the user approves a final read-only representation of the exact content sent;
- local and server code independently recompute the same canonical content hash;
- direct database RPC calls cannot bypass Edge authentication;
- manual approval and trusted release create a durable, idempotent outbox entry;
- the remote queue has claim, retry, completion, dead-letter, and status paths;
- record-only items are stored/exported and never executed;
- OpenClaw works end to end, while unavailable Hermes support is clearly disabled;
- spreadsheet output is complete, concurrency-safe, idempotent, and protected from formula injection;
- local state, note frontmatter, broker state, and consumer result reconcile correctly after failures and restarts;
- migrations apply from scratch and upgrade existing databases safely;
- the full local and GitHub test/security suites pass without hanging;
- synthetic staging passes before any real-data rollout;
- operators have monitoring, secret rotation, disable, retry, retention, and rollback procedures.

## 9. Decisions the maintainer must confirm

These choices affect product behaviour and should be written down before the related PR begins:

1. Which spreadsheet/database is the production record destination: local CSV, Google Sheets, Airtable, Supabase table, or another service?
2. Is full transcript inclusion permitted at all in the expected environment, and what is its retention period?
3. Is Telegram governed by the same master sharing mode?
4. Which accounts/devices may use `trusted_auto`, and is server-side entitlement required?
5. What exact rules should always pause trusted mode besides a high-risk assessment?
6. What is the expected OpenClaw v2 contract?
7. Is Hermes in scope now, or should it remain unavailable until a separate integration milestone?
8. Where will the remote worker run, and who owns queue/dead-letter monitoring?
9. How long should local reviews, broker records, payloads, and spreadsheet rows be retained?
10. What is the emergency behaviour for already queued items when the user switches sharing to off?

Until these decisions are confirmed, use the safest defaults: sharing off, transcript excluded, high-risk pause on, unsupported targets rejected, and queued items held for explicit operator action during an emergency stop.
