# Outbound lifecycle and safe-receipt contract

## Scope

This milestone projects task lifecycle metadata and safe external receipt
identifiers. It does not project arbitrary agent deliverables or agent response
Markdown.

The teacher-facing lifecycle is:

`Submitted → Claimed → Completed`

or:

`Submitted → Claimed → Blocked`

Local transmission failures may enter `Blocked` before broker submission and
carry a fixed local reason code.

## Authoritative source and mapping

`public.cvn_outbound_items` remains the authoritative remote lifecycle table.
The desktop reads it only through `cvn-outbound-status`, which authenticates the
desktop client, scopes the lookup to its `source_device_id`, and calls the
canonical `cvn_get_outbound_item_status` RPC with `service_role`.

| Remote status | Desktop lifecycle |
| --- | --- |
| `submitted`, `received`, `failed_retryable` | Submitted |
| `claimed`, `claiming`, `processing` | Claimed |
| `completed` | Completed |
| `failed_permanent`, `dead_letter`, `expired` | Blocked |

The local projection is monotonic and idempotent. Terminal `Completed` and
`Blocked` states do not regress. The desktop persists `submitted_at`,
`claimed_at`, `completed_at` or `blocked_at`, `safe_receipt`, and a bounded
`blocked_reason` code in `external_outbox.db`. It never copies remote
`result_json`, free-form result summaries, transcripts, email bodies, or task
content into lifecycle fields.

`claimed_at` is historical lifecycle evidence, not lease ownership. Clearing a
lease must clear the worker and lease fields but preserve the most recent claim
timestamp.

## OpenClaw result contract

OpenClaw must return exactly one line after the action tool reports its outcome.

Successful action:

```text
ACTION_COMPLETED: receipt_type=<safe_type>; receipt_id=<safe_identifier>
```

AgentMail example:

```text
ACTION_COMPLETED: receipt_type=agentmail_message_id; receipt_id=msg_abc-123
```

Blocked action:

```text
ACTION_BLOCKED: reason_code=<UPPERCASE_REASON_CODE>
```

Ambiguous side-effect outcome:

```text
ACTION_UNKNOWN: reason_code=<UPPERCASE_REASON_CODE>
```

`receipt_type` is a lowercase identifier. `receipt_id` is at most 256
characters and may contain only letters, digits, `.`, `_`, `:`, `@`, `/`, `+`,
or `-`. The worker converts the first form to the canonical
`<receipt_type>:<receipt_id>` `result_reference`. It discards the raw agent
output. Free-form output fails validation and is never stored, transmitted as
result telemetry, or written to Obsidian.

`ACTION_BLOCKED` is terminal and becomes the remote `dead_letter`/desktop
`Blocked` state. `ACTION_UNKNOWN` is quarantined so an uncertain side effect is
not repeated automatically.

## Desktop and Obsidian projection

The desktop lifecycle dialog reads a lifecycle-only SQLite query that excludes
`payload_json`. It shows task ID, current state, timestamps, safe receipt or
blocked reason, attempt count, transport state, and last status check.

The originating Obsidian note receives the same metadata in `external_*`
frontmatter keys and one replace-in-place `Outbound lifecycle` block. Projection
is atomic and idempotent. It accepts only validated timestamps, safe receipts,
and fixed reason codes.

## Privacy invariants

- No raw transcript, email body, recipient, subject, classroom content, agent
  prose, or tool output is lifecycle telemetry.
- Receipt validation fails closed. An invalid `result_reference` is discarded.
- Failure text is reduced to a bounded machine reason code before projection.
- Audit events contain only task IDs, state names, counts, durations, and fixed
  error codes.
- Arbitrary deliverable Markdown remains deferred until after Gate B.
