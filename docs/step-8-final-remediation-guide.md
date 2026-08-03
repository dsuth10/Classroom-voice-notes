# Step 8 Final Remediation Guide

## Purpose

This guide completes Step 8 of the outbound-sharing go-live work. It is written for a junior engineer and should be followed in order.

The goal is to leave the transactional SQLite record store and generated CSV export ready for senior approval. Do not begin Step 9 until every acceptance check at the end of this document passes.

## Current baseline

Start from commit:

```text
8df0a2cb05ec0eef6c22ab66c3e841348b58bdd7
```

The following parts are already implemented and should be preserved:

- SQLite is the authoritative record store.
- Schema version 2 upgrades the previous version 1 database without losing records.
- Canonical content hashes are recomputed before opening the write transaction.
- Inserts are transactional and idempotent by `item_id` and `content_hash`.
- CSV generation uses a temporary file, flush, `fsync`, and atomic replacement.
- CSV generation is protected by an inter-process file lock.
- Failed exports return `export_pending` and can be retried.
- Missing CSV files trigger regeneration.
- Multiprocess tests verify that child processes finish successfully.

Do not redesign these working areas unless a new failing test proves that a change is necessary.

## Remaining problems

Four related issues remain:

1. GitHub CI fails because an older test constructs an incomplete payload.
2. `validate_payload_v2()` silently invents missing identity, timestamp, and privacy fields.
3. Local enum values do not match the established `cvn.outbound_item.v2` contract.
4. Claimed records do not currently have to provide their broker-approved `content_hash`.

The remediation must reject incomplete or contradictory claimed payloads. Do not add compatibility defaults to the production consumer.

## Required implementation order

### 1. Record the baseline failure

From the repository root, run:

```powershell
uv run --frozen pytest tests/unit/test_outbound_integration_pr12.py::test_pr12_record_consumer_idempotency_recovery -v
```

Expected baseline result:

```text
ValueError: Payload missing valid non-empty target_agent string
```

This failure is caused by an obsolete test fixture. It is not evidence that production validation should be relaxed.

### 2. Define the exact record-consumer contract

Edit:

```text
app/destinations/record_db.py
```

Replace the current release-basis constants with values used by the existing v2 builder, submission service, and Edge Function:

```python
ALLOWED_RELEASE_BASES = {
    "automatic_policy",
    "human_approval",
    "trusted_mode",
}

ALLOWED_CLASSIFICATIONS = {
    "non_sensitive",
    "sensitive_pii",
    "safeguarding",
    "medical",
    "sensitive",
}

ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_TARGET_AGENTS = {"openclaw"}
```

Before committing these values, compare them with:

- `app/destinations/outbound_submission_service.py`
- `app/destinations/outbound_payload_builder.py`
- `supabase/functions/cvn-submit-outbound-item/index.ts`

All four locations must agree. Do not introduce alternative names such as `policy_auto_release` or `trusted_auto_release`.

If these values cannot be made consistent without changing the public contract, stop and ask the senior engineer before proceeding.

### 3. Make payload validation pure and fail-closed

Refactor `validate_payload_v2()` so it only validates. It must not add, replace, normalize, or default values in the input dictionary.

Remove behavior that writes any of the following:

```python
payload["schema_version"] = ...
payload["source_device_id"] = ...
payload["created_at"] = ...
payload["privacy"] = ...
privacy["release_basis"] = ...
privacy["automatic_classification"] = ...
```

Missing information must raise `ValueError` before a SQLite transaction is opened.

#### Required top-level validation

Require all of the following:

| Field | Rule |
| --- | --- |
| `schema_version` | Must equal `cvn.outbound_item.v2`. |
| `item_id` | Must be a non-empty string. Prefer the established CVNI identifier pattern if it is already shared by the application. |
| `item_kind` | Must equal `record_only`. |
| `target_agent` | Must be in `ALLOWED_TARGET_AGENTS`. |
| `source_device_id` | Must be a non-empty string. Do not accept `unknown_device`. |
| `created_at` | Must be a timezone-aware ISO 8601 timestamp. |
| `content_hash` | Must be a lowercase 64-character hexadecimal SHA-256 value. |
| `content` | Must be a dictionary. |
| `privacy` | Must be a dictionary. |
| `task` | Must be absent, `None`, or the one empty representation accepted by the documented v2 contract. It must never contain instructions. |

Do not accept legacy `source_device` in newly claimed payloads. The database migration may preserve old stored data, but the live v2 payload contract uses `source_device_id`.

#### Required content validation

Validate these fields before beginning the transaction:

| Field | Rule |
| --- | --- |
| `title` | Required, string, and non-empty after trimming. |
| `summary` | Optional; when present, must be a string. |
| `category` | Optional; when present, must be a string. |
| `recorded_at` | Optional only if the product contract permits it; when present, must be timezone-aware ISO 8601. |
| `duration_seconds` | Optional; when present, must be numeric, finite, and at least zero. Reject booleans. |
| `tags` | Optional; when present, must be a list of strings. |
| `structured_fields` | Optional; when present, must be a dictionary with string keys and JSON-compatible values. |
| `transcript` | Optional; when present, must be a string. Absence must remain absence. |

Python treats `bool` as a subclass of `int`. Explicitly reject boolean durations:

```python
if isinstance(duration, bool) or not isinstance(duration, (int, float)):
    raise ValueError(...)
```

Reject `NaN`, positive infinity, and negative infinity using `math.isfinite()`.

#### Required privacy validation

Require and validate:

| Field | Rule |
| --- | --- |
| `automatic_classification` | Must be in `ALLOWED_CLASSIFICATIONS`. |
| `risk_level` | Must be in `ALLOWED_RISK_LEVELS`. |
| `release_basis` | Must be in `ALLOWED_RELEASE_BASES`. |

For `human_approval` and `trusted_mode`, require a `privacy.approval` dictionary containing:

- a valid timezone-aware `approved_at` timestamp;
- a lowercase 64-character `approved_content_hash`;
- `approved_content_hash` equal to the payload `content_hash`.

For `automatic_policy`, require the existing contract's non-empty `checks_passed` list and validate that each entry is a string. Do not invent checks locally.

The consumer should not attempt to re-authorize trusted mode. It should only reject a malformed claimed envelope.

### 4. Add a timezone-aware timestamp helper

Keep timestamp validation small and testable. A suitable private helper can follow this shape:

```python
def _require_aware_iso8601(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a timezone-aware ISO 8601 timestamp")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a timezone-aware ISO 8601 timestamp"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")

    return parsed
```

Do not replace a missing timestamp with the current time. That would create inaccurate audit evidence.

### 5. Require and verify the claimed content hash

In `RecordDatabase.insert_record()`:

1. Run `validate_payload_v2(payload)`.
2. Read the required `payload["content_hash"]`.
3. Recompute the RFC 8785 canonical hash using `compute_canonical_content_hash()`.
4. Compare using exact lowercase values.
5. Raise `ValueError` on mismatch before opening SQLite.
6. Store the recomputed hash only after equality is established.

The validation should resemble:

```python
caller_hash = payload.get("content_hash")
if not isinstance(caller_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", caller_hash):
    raise ValueError("content_hash must be a lowercase 64-character SHA-256 value")

if caller_hash != computed_hash:
    raise ValueError("content_hash does not match recomputed canonical content hash")
```

Do not include either complete hash in the public exception text. The audit system can identify the item using `item_id` without logging supplied values.

### 6. Update obsolete tests with real v2 payloads

Edit:

```text
tests/unit/test_outbound_integration_pr12.py
```

Update `test_pr12_record_consumer_idempotency_recovery` to construct its payload through `build_outbound_payload_v2()` instead of a hand-written partial dictionary.

Use only synthetic values. The fixture should include:

- an item ID;
- a synthetic source device ID;
- `record_only`;
- `openclaw`;
- title and summary;
- `non_sensitive` classification;
- `low` risk;
- `human_approval`;
- approval metadata generated by the builder;
- no transcript unless the test specifically needs one.

Preserve the original purpose of the test:

- first delivery stores one record;
- repeated identical delivery returns idempotent success;
- the database and CSV contain one logical record.

Do not manually add defaults to the fixture after calling the builder. If the builder cannot produce a valid payload, correct the shared contract mismatch rather than working around it in the test.

### 7. Expand strict-validation regression tests

Add focused cases to:

```text
tests/unit/test_record_db.py
```

Use a valid payload from `build_outbound_payload_v2()` as the starting point. Deep-copy it before each mutation so tests cannot affect one another.

Add one test for every rejection below:

- missing `schema_version`;
- wrong `schema_version`;
- missing or unsupported `target_agent`;
- missing `source_device_id`;
- missing or naive `created_at`;
- malformed `created_at`;
- missing `content_hash`;
- uppercase or malformed `content_hash`;
- mismatched `content_hash`;
- missing `privacy`;
- unsupported classification;
- unsupported risk level;
- unsupported release basis;
- missing approval for human approval;
- approval hash mismatch;
- malformed or timezone-less approval timestamp;
- non-string tag;
- non-string structured-field key;
- boolean, negative, NaN, or infinite duration;
- non-string transcript;
- executable task content in a record-only item.

Also add a purity assertion:

```python
before = copy.deepcopy(payload)
validate_payload_v2(payload)
assert payload == before
```

For rejection cases, assert the payload is still identical to its pre-validation copy after the exception.

### 8. Preserve and rerun migration tests

Do not edit the already-applied meaning of schema version 1. Preserve the version-2 migration currently implemented in `RecordDatabase._init_db()`.

The migration tests must continue to prove:

- a fresh database reaches version 2;
- a real version-1 database upgrades to version 2;
- an existing row and its source device value survive;
- `source_device_id` and `export_status` exist afterward;
- a new valid v2 record can be inserted after upgrade;
- reopening a version-2 database is idempotent;
- a forced migration exception rolls the complete migration back.

If rollback coverage does not already exist, add it before senior review.

### 9. Verify export recovery remains intact

Run and preserve tests covering:

- CSV export failure returns `export_pending`;
- the committed SQLite row remains present;
- retry clears pending status;
- deleting the CSV triggers regeneration even when all rows were previously exported;
- concurrent processes all exit with code zero;
- the final CSV parses and contains every expected item exactly once.

Do not couple CSV export success to the SQLite transaction. SQLite remains authoritative.

## Required verification sequence

Run these commands from the repository root in this order.

### Focused validation tests

```powershell
uv run --frozen pytest tests/unit/test_record_db.py -v
```

### Consumer and recovery tests

```powershell
uv run --frozen pytest tests/unit/test_record_consumer.py tests/unit/test_record_concurrency_failure.py -v
```

### Updated legacy regression

```powershell
uv run --frozen pytest tests/unit/test_outbound_integration_pr12.py::test_pr12_record_consumer_idempotency_recovery -v
```

### Entire Step 8 set

```powershell
uv run --frozen pytest tests/unit/test_record_db.py tests/unit/test_record_consumer.py tests/unit/test_record_concurrency_failure.py tests/unit/test_record_consumer_pr8.py tests/unit/test_record_export_pr9.py tests/unit/test_outbound_integration_pr12.py -v
```

### Static checks

```powershell
uv run --frozen ruff check app tests scripts run.py
uv run --frozen mypy app
git diff --check
```

### Full Python suite

```powershell
uv run --frozen pytest tests -p no:cacheprovider
```

The full suite must report zero failures. Credential-dependent staging tests may skip for documented reasons.

### Deno checks

Step 8 is primarily Python, but the repository release gate still includes the existing TypeScript checks:

```powershell
deno fmt --check supabase/functions
deno check supabase/functions/_shared/*.ts supabase/functions/cvn-claim-outbound-item/index.ts supabase/functions/cvn-claim-task/index.ts supabase/functions/cvn-complete-outbound-item/index.ts supabase/functions/cvn-complete-task/index.ts supabase/functions/cvn-fail-outbound-item/index.ts supabase/functions/cvn-fail-task/index.ts supabase/functions/cvn-outbound-status/index.ts supabase/functions/cvn-status/index.ts supabase/functions/cvn-submit-outbound-item/index.ts supabase/functions/cvn-submit-task/index.ts
deno test --allow-env supabase/functions/_shared/outbound_contract_test.ts
```

## Git and GitHub procedure

1. Confirm only intended Step 8 files changed:

   ```powershell
   git status --short
   git diff --stat
   git diff --check
   ```

2. Review the actual diff. Pay particular attention to accidental defaults and payload mutation.
3. Commit the remediation with a message that describes the contract hardening and regression repair.
4. Push the branch or synchronized main branch according to the repository's normal workflow.
5. Open the exact GitHub Actions run for the new commit.
6. Confirm both jobs pass:

   - `Quality and tests (Python 3.11)`
   - `Secret scan`

7. Record the commit hash and Actions URL in the Step 8 walkthrough.

Local success is not sufficient if the exact GitHub commit is red.

## Acceptance checklist

Step 8 is ready for another senior review only when every box is checked:

- [ ] GitHub Actions is green for the exact reviewed commit.
- [ ] Secret scanning passes.
- [ ] The full Python suite has zero failures.
- [ ] `validate_payload_v2()` does not mutate its input.
- [ ] Missing schema, device, timestamp, privacy, or content hash is rejected.
- [ ] Release-basis values exactly match the established v2 contract.
- [ ] Classification and risk values match the desktop submission contract.
- [ ] All required timestamps include a timezone.
- [ ] The supplied lowercase content hash is mandatory and equals the recomputed hash.
- [ ] The old PR12 regression uses the real v2 builder and passes.
- [ ] Fresh schema creation reaches version 2.
- [ ] Version-1 upgrade preserves records and reaches version 2.
- [ ] Reopening version 2 performs no destructive migration.
- [ ] Export failure remains independently retryable.
- [ ] Missing CSV regeneration passes.
- [ ] Multiprocess export produces one complete, parseable CSV.
- [ ] Ruff, mypy, Deno checks, and `git diff --check` pass.
- [ ] Only synthetic test data appears in tests and logs.

## Stop and ask for senior help when

Stop rather than guessing if any of these occur:

- the accepted classification or release-basis values differ between Python and Edge code;
- a legacy producer still sends partial non-v2 payloads in production;
- preserving a legacy database requires deleting or reinterpreting stored information;
- a migration cannot be made transactional;
- a test passes only after adding a production default for missing approval or identity fields;
- an error can be diagnosed only by logging transcript or other payload content;
- transcript inclusion or retention rules are unclear;
- the full suite or exact GitHub Actions run remains red.

## Senior handoff package

Provide the reviewer with:

1. the final commit hash;
2. the green GitHub Actions URL;
3. the full-suite pass count and documented skips;
4. the fresh-install and version-1 upgrade test results;
5. the strict-validation test list;
6. confirmation that validation does not mutate payloads;
7. the CSV failure/retry and multiprocess results;
8. any accepted residual risks and the person who approved them.

After the senior reviewer confirms this checklist, mark Step 8 complete and proceed to Step 9.
