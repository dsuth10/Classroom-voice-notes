# Outbox Recovery

The local outbox provides durable delivery and status tracking for approved
external agent tasks.

On Windows, its database is:

```text
%LOCALAPPDATA%\ClassroomVoiceNotes\external_outbox.db
```

The associated audit log is:

```text
%LOCALAPPDATA%\ClassroomVoiceNotes\logs\audit.log
```

Do not open the database in a write-capable SQLite editor or modify task rows
manually.

## Status meanings

| Status | Meaning | Normal action |
| --- | --- | --- |
| `pending` | Waiting for its next eligible send | Allow automatic retry or use **Retry Outbox Now** |
| `sending` | A bounded send attempt is active | Wait for completion |
| `sent` | Accepted by the broker | Allow status reconciliation |
| `processing` | Claimed or running remotely | Allow status reconciliation |
| `completed` | Finished successfully | Review the originating note |
| `failed` | Remote task ended unsuccessfully | Review the sanitised error and note |
| `dead_letter` | Automatic delivery stopped | Selectively retry or archive after review |
| `archived` | Retained locally and excluded from retry | No transmission |

Pending or sending records older than seven days are moved to `dead_letter`
before another retry is attempted.

## Normal recovery workflow

1. Confirm the active environment:

   ```powershell
   $env:CVN_BROKER_ENV
   ```

   It must be exactly `staging` for current operations.

2. Open CVN settings and verify the broker endpoint matches:

   ```text
   https://ukqkkgzimhtjhlnmlyao.supabase.co/functions/v1/cvn-submit-task
   ```

3. Review the live outbox counts.

4. Use **Retry Outbox Now** only for eligible pending work. This action does
   not revive dead-letter tasks.

5. Use **View Outbox** to inspect dead-letter records. The interface displays
   safe metadata such as task ID, dates, attempts and a sanitised error.

6. Select one dead-letter task and choose:

   - **Retry Selected Task** when the task is still valid and the environment
     and endpoint are correct; or
   - **Archive Selected Task** when the task is obsolete or must not be sent.

7. Confirm the action in the dialogue.

8. Review the originating Obsidian note and audit log for the resulting state.

## When selective retry is appropriate

Retry only when all of these conditions hold:

- the task is still required;
- its content is synthetic or already approved as non-sensitive;
- the active environment matches the stored endpoint;
- staging credentials are valid;
- the original failure was operational rather than a privacy-policy block; and
- a duplicate execution would not create an unsafe external side effect.

A broker `409` duplicate response is reconciled as sent because the broker
already holds the idempotent task.

## When to archive

Archive when:

- the task is obsolete;
- it was a historical synthetic test;
- its intended action is no longer wanted;
- the environment cannot be verified;
- the error suggests a permanent validation failure; or
- an operator cannot establish that replay is safe.

Archiving preserves local audit history without retransmitting the payload.

## Fail-closed protections

Before retry or status access, CVN revalidates the stored endpoint against the
active environment. It rejects:

- the wrong Supabase project;
- HTTP;
- alternate ports;
- lookalike or embedded-credential hosts;
- paths outside `/functions/v1/`;
- query strings; and
- URL fragments.

An endpoint-validation failure moves pending work to dead letter without a
network request.

## Safe read-only inspection

If the UI cannot open, an operator may inspect safe columns without selecting
payload, nonce, hashes or idempotency data:

```powershell
@'
import os
import sqlite3
from pathlib import Path

database = Path(os.environ["LOCALAPPDATA"]) / "ClassroomVoiceNotes" / "external_outbox.db"
connection = sqlite3.connect(database)
rows = connection.execute("""
    SELECT local_id, task_id, created_at, target_agent, status,
           attempt_count, next_retry_at, sent_at
    FROM outbox
    ORDER BY local_id
""").fetchall()
connection.close()

for row in rows:
    print(" | ".join("" if value is None else str(value) for value in row))
'@ | uv run python -
```

This inspection is read-only. Do not add `UPDATE`, `DELETE`, payload columns or
credential output.

## Escalation

Stop recovery and investigate when:

- multiple tasks unexpectedly dead-letter together;
- authentication begins failing;
- the endpoint environment is ambiguous;
- the VPS worker or gateway restarted unexpectedly;
- a task remains claimed beyond its visibility timeout;
- the originating note contains unexpected remote content; or
- any classroom data or credential may have left the local boundary.

Do not weaken the policy gate, switch to production, expose the gateway, bypass
RLS or use a service-role key to recover an outbox task.
