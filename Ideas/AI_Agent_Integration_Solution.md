# Milestone 2 — Remote Agent Task Consumption

You have completed:

```text
Milestone 1:
CVN can safely submit approved, non-sensitive tasks to the Supabase broker.

App-side Phase 1:
Classroom Voice Notes can build, sign, queue, retry, and dispatch safe broker payloads.
```

The next milestone is about what happens **after a task lands in Supabase**.

The aim is:

```text
Supabase broker receives task
→ remote VPS/agent claims task
→ agent processes task
→ agent reports completion or failure
→ broker records status and audit trail
→ CVN can later check status
```

## Guiding principle

Do **not** jump straight to full Hermes/OpenClaw automation.

Build the next phase in three controlled layers:

```text
2A. Supabase broker endpoints
2B. Dummy VPS poller
2C. Real Hermes/OpenClaw routing
```

That way, you prove the queue mechanics before giving a real agent responsibility.

---

# Phase 2A — Supabase Broker Consumption API

## Goal

Add the minimum broker-side functions needed for a remote worker to consume tasks safely.

The current broker can receive tasks. It now needs to support:

```text
claim task
mark running
mark complete
mark failed
check status
handle stale claims
handle repeated failures
```

## New Edge Functions

Create these on **staging first**:

```text
cvn-claim-task
cvn-complete-task
cvn-fail-task
cvn-status
```

Do not touch production until staging passes.

---

## 1. `cvn-claim-task`

### Purpose

Allows the remote VPS worker to ask:

```text
Is there a task waiting for me?
```

### Expected behaviour

The function should:

```text
1. Authenticate the VPS worker.
2. Read one pending task from pgmq.
3. Mark the corresponding cvn_tasks row as claimed or running.
4. Record a cvn_task_events entry.
5. Return the safe task payload.
6. Return nothing if no task is available.
```

### Suggested response when a task exists

```json
{
  "claimed": true,
  "task_id": "CVN-20260709-113316-L6LY",
  "target_agent": "hermes",
  "status": "claimed",
  "payload": {
    "schema_version": "cvn.agent_task.v1",
    "task": {
      "title": "...",
      "instructions": "..."
    }
  }
}
```

### Suggested response when no task exists

```json
{
  "claimed": false,
  "reason": "no_pending_tasks"
}
```

## Important claim rules

Only one worker should claim a task.

Use pgmq’s visibility timeout properly. A claim should make the queue message temporarily invisible while the worker processes it.

Recommended claim window:

```text
30 minutes
```

If the worker crashes and does not complete/fail the task, the reaper can return it to pending later.

---

## 2. `cvn-complete-task`

### Purpose

Allows the remote worker to say:

```text
I successfully completed this task.
```

### Expected behaviour

The function should:

```text
1. Authenticate the worker.
2. Confirm task exists.
3. Confirm task is claimed/running.
4. Update cvn_tasks.status to completed.
5. Store a short result_summary.
6. Record a completed event.
7. Archive or remove the pgmq message.
8. Return success.
```

### Suggested request body

```json
{
  "task_id": "CVN-20260709-113316-L6LY",
  "worker_id": "vps-joshua-worker-001",
  "result_summary": "Completed fake test task successfully.",
  "completed_at": "2026-07-09T12:10:00+10:00"
}
```

### Result summary rule

Keep the result summary short and safe.

Do **not** allow the worker to post large files, raw transcripts, private data, or agent logs back into this table.

---

## 3. `cvn-fail-task`

### Purpose

Allows the worker to say:

```text
I tried this task, but it failed.
```

### Expected behaviour

The function should:

```text
1. Authenticate the worker.
2. Confirm task exists.
3. Increment retry_count.
4. Record failure event.
5. If retry_count < max, return task to pending.
6. If retry_count >= max, mark dead_letter.
```

Recommended retry limit:

```text
5 attempts
```

### Suggested statuses

```text
pending
claimed
running
completed
failed
dead_letter
cancelled
```

You already have these status ideas in the broker. Keep them consistent.

---

## 4. `cvn-status`

### Purpose

Allows CVN to ask:

```text
What happened to the task I submitted?
```

This is not urgent for the first poller, but it should be designed now so the schema is ready.

### Suggested response

```json
{
  "task_id": "CVN-20260709-113316-L6LY",
  "status": "completed",
  "target_agent": "hermes",
  "created_at": "...",
  "claimed_at": "...",
  "completed_at": "...",
  "result_summary": "Completed successfully."
}
```

For privacy, the status endpoint should not return the full original payload unless there is a strong reason.

---

# Phase 2A Security Model

Use **separate secrets** for the remote worker.

Do not reuse the CVN submit secrets.

Recommended secret split:

```text
CVN → Supabase submit:
  CVN_HMAC_SECRET
  CVN_BEARER_TOKEN

VPS agent → Supabase broker:
  AGENT_BROKER_HMAC_SECRET
  AGENT_BROKER_BEARER_TOKEN
```

The worker should never receive:

```text
Supabase service role key
database password
personal access token
CVN local keyring secrets
raw classroom notes
student registry
Obsidian vault access
```

The Edge Functions use the service role key internally. The VPS worker only gets the limited broker credentials.

---

# Phase 2A Database Work

Create new migrations, not edits to the old frozen files.

Possible migrations:

```text
004_cvn_claim_complete_fail_functions.sql
005_cvn_reaper_jobs.sql
```

Do not modify:

```text
001_cvn_broker_mvp.sql
002_pgmq_schema_grants.sql
003_cvn_submit_task_security_definer.sql
```

Those are now production history.

## Stored procedures to consider

Instead of putting all logic inside Edge Function TypeScript, use SQL RPCs for atomic database work:

```text
cvn_claim_next_task(...)
cvn_complete_task(...)
cvn_fail_task(...)
cvn_reap_stale_claims(...)
```

This keeps race-sensitive queue operations inside the database transaction.

---

# Phase 2A Staging Test Matrix

Before production, staging should prove:

```text
1. Claim with no tasks returns claimed=false.
2. Claim with one pending task returns exactly one task.
3. Two workers claiming at the same time do not get the same task.
4. Complete marks task completed.
5. Complete is idempotent if called twice.
6. Fail increments retry_count.
7. Fail below retry limit returns task to pending.
8. Fail at retry limit marks dead_letter.
9. Stale claimed task can be reaped.
10. Status endpoint returns safe status only.
11. Wrong worker bearer token returns 401.
12. Tampered worker request returns 401.
13. Missing task_id returns 400.
14. No full sensitive payload is returned through status.
```

Acceptance target:

```text
All Phase 2A staging tests pass before any production deploy.
```

---

# Phase 2B — Dummy VPS Poller

## Goal

Before Hermes/OpenClaw actually process tasks, build a tiny dummy worker that proves the lifecycle.

The dummy worker should:

```text
1. Poll cvn-claim-task every 5–10 seconds.
2. If no task, sleep.
3. If task claimed, log the task_id.
4. Wait 2 seconds.
5. Call cvn-complete-task with a fake result summary.
```

This proves:

```text
Supabase queue works
claiming works
completion works
worker auth works
status changes work
```

No real AI yet.

## Dummy worker file

Suggested file:

```text
watch_inbox_dummy.py
```

Run it on the VPS or local development machine first.

## Dummy worker safety

The dummy worker should have a hardcoded environment variable guard:

```text
CVN_BROKER_ENV=staging
```

It should refuse to run against production unless explicitly set:

```text
CVN_BROKER_ENV=production
CVN_ALLOW_PRODUCTION_WORKER=true
```

That prevents accidental production queue consumption.

---

# Phase 2C — Real Hermes/OpenClaw Routing

Only after the dummy worker passes should the real worker route tasks.

## Worker flow

```text
claim task
→ inspect target_agent
→ route to Hermes or OpenClaw
→ send safe task instructions as the user message
→ wait for result
→ complete or fail task
```

## Target agent handling

Recommended behaviour:

```text
target_agent = hermes:
  planning, research, task design, documentation

target_agent = openclaw:
  code changes, repo work, implementation, tests

target_agent = auto:
  worker chooses route based on task title/instructions
```

## Do not let the worker fetch extra private context

The worker should process only the safe payload it receives.

It should not have access to:

```text
local Obsidian vault
student registry
raw transcript
audio files
teacher private notes
Classroom Voice Notes local database
```

---

# Phase 2D — CVN Status Polling Later

This is not the first coding task, but it is the natural follow-up.

Once broker consumption is working, CVN can add:

```text
task status polling
completed/failed indicators
manual refresh
result summary display
dead-letter awareness
```

Do not build this until `cvn-status` is stable.

---

# Recommended Coding Order

Give OpenClaw this order:

```text
1. Write Phase 2A technical spec.
2. Implement staging-only Supabase migrations for claim/complete/fail/status.
3. Implement Edge Functions.
4. Add broker-side tests.
5. Deploy to staging.
6. Run staging HTTP tests.
7. Build dummy poller.
8. Run dummy poller against staging.
9. Promote Phase 2A to production only after staging is clean.
10. Run dummy poller against production using fake tasks only.
11. Then design real Hermes/OpenClaw worker routing.
```

---

# What Not To Do Yet

Do not:

```text
start live classroom use
connect the production VPS worker immediately
consume production queue messages automatically
delete diagnostic/test queue rows
disable append-only audit triggers
give the worker Supabase service role access
send raw transcripts
send student data
send behaviour/welfare/medical/parent information
build result display in CVN before status endpoint exists
merge risky Milestone 2 code into main without a new tag
```

---

# Definition of Done for Milestone 2

Milestone 2 is complete when:

```text
Supabase:
  claim, complete, fail, and status endpoints exist
  all are authenticated
  all are tested
  stale claims are handled
  dead-letter behaviour works

Worker:
  dummy poller successfully claims and completes fake tasks
  real worker can route to Hermes/OpenClaw safely
  worker never receives sensitive classroom data

CVN:
  submit path remains stable
  local outbox still works
  no double-sending to Telegram
  status polling is either implemented safely or explicitly deferred

Audit:
  every claim, complete, fail, retry, and dead-letter transition is logged
```

---

# Immediate Next Instruction for OpenClaw

You can send this:

```text
We are beginning CVN Broker Milestone 2 planning only.

Current stable state:
- main is merged and tagged as cvn-broker-phase-1-complete.
- CVN can submit safe non-sensitive tasks to production Supabase.
- external_agent.enabled is false by default.
- no VPS worker is connected yet.

Your next task is not to code immediately. First, produce a Milestone 2 technical design for:
1. cvn-claim-task
2. cvn-complete-task
3. cvn-fail-task
4. cvn-status
5. stale claim reaper
6. dummy VPS poller
7. later Hermes/OpenClaw routing

Constraints:
- staging first
- no production worker yet
- no real classroom data
- no raw transcripts
- no student data
- no service role key on the VPS worker
- use separate AGENT_BROKER_HMAC_SECRET and AGENT_BROKER_BEARER_TOKEN
- do not modify frozen Milestone 1 migrations
- new work must be in new migrations/functions only

Please return:
- proposed schema/function changes
- endpoint contracts
- auth model
- retry/dead-letter design
- staging test matrix
- rollback plan
- exact implementation order
```

That is the next step: **design Milestone 2 before writing code.**
