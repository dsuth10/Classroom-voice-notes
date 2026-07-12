# Phase 2C.1 Staging Verification & Deployment Report

**Project:** Classroom Voice Notes (CVN) Broker  
**Environment:** Supabase staging only (`ukqkkgzimhtjhlnmlyao`)  
**Execution Host:** Windows Local Development Machine  
**Date:** 12 July 2026  

---

## 1. Frozen Git State

- **Branch Name:** `feature/phase-2c-worker-identities`
- **Commit Hash:** `d6790949029c6775b95094a0bfca84a72cb6ae73`
- **`git status --short`:** clean (nothing to commit, working tree clean)
- **Changed-File List:**
  - [app/worker/broker_worker.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/app/worker/broker_worker.py)
  - [docs/architecture/003-cvn-worker-contract.md](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/docs/architecture/003-cvn-worker-contract.md)
  - [supabase/functions/_shared/broker_auth.ts](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/supabase/functions/_shared/broker_auth.ts)
  - [supabase/functions/cvn-claim-task/index.ts](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/supabase/functions/cvn-claim-task/index.ts)
  - [supabase/functions/cvn-complete-task/index.ts](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/supabase/functions/cvn-complete-task/index.ts)
  - [supabase/functions/cvn-fail-task/index.ts](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/supabase/functions/cvn-fail-task/index.ts)
  - [supabase/functions/cvn-status/index.ts](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/supabase/functions/cvn-status/index.ts)
  - [supabase/migrations/007_cvn_phase_2c1_auth_extensions.sql](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/supabase/migrations/007_cvn_phase_2c1_auth_extensions.sql)
  - [tests/integration/test_supabase_broker_extensions.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/integration/test_supabase_broker_extensions.py)
  - [tests/integration/test_worker_identities.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/tests/integration/test_worker_identities.py)
  - [watch_inbox_dummy.py](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/watch_inbox_dummy.py)
- **Migration 007 SHA-256 Checksum:** `854514743BC573A4F55D3DF4F545DBA1C8D716BDF1873A3A69ACBB0E1D6FA24B`

---

## 2. Devlopment State & Checked Deviations

1. **Commit af871feb095c9bae03772c8644095d2bbab68354 status:**
   - *Deviation:* Did not contain the `sha256Hex` export correction.
   - *Resolution:* Amended the feature branch commit to include the export correction (`export async function sha256Hex`), updated integration tests, and the new rotation/disablement tests in a single clean commit (`d6790949029c6775b95094a0bfca84a72cb6ae73`).
2. **Unclean Working Tree:**
   - *Deviation:* Deployed from a dirty working copy during initial test run.
   - *Resolution:* Created a clean commit matching the deployed source, verified that the working tree is completely clean (`git status --short` is empty), and repeated the Edge Function deployments and all test runs from this clean commit.
3. **Missing Rotation/Disablement Tests:**
   - *Deviation:* No automated tests existed for credential lifecycle management.
   - *Resolution:* Added `test_credential_disable_rotation()` in `test_worker_identities.py` which dynamically rotates and disables credentials via the Supabase CLI, asserts status codes, verifies that old credentials return 401, re-enables credentials to verify success, and restores the original registry baseline in a self-cleaning `finally` block.
4. **Extensions Test (OpenClaw target):**
   - *Deviation:* `tests/integration/test_supabase_broker_extensions.py` attempted to claim an `openclaw` task using legacy credentials, which was rejected under Phase 2C.1 rules.
   - *Resolution:* Updated the test to send the registered key ID (`test-openclaw-worker-01`) for all openclaw tasks.

---

## 3. Staging Deployment Commands

The controlled deployment was performed using the following CLI sequences:

### 3.1. Database Migration
```bash
# Verify linked project and run database push
npx supabase db push --linked
```
**Output:**
```text
Initialising login role...
Connecting to remote database...
Do you want to push these migrations to the remote database?
 • 007_cvn_phase_2c1_auth_extensions.sql

 [Y/n] 
Applying migration 007_cvn_phase_2c1_auth_extensions.sql...
Finished supabase db push.
```

### 3.2. Registry Secret Configuration
To prevent exposing the registry JSON in the process command line or terminal history, the secrets were loaded into staging using a temporary `.env` file via the CLI's `--env-file` flag. The file was overwritten with zeroes and removed immediately after execution:
```bash
npx supabase secrets set --env-file scratch/temp_secrets.env --project-ref ukqkkgzimhtjhlnmlyao
```

### 3.3. Edge Function Deployment
```bash
npx supabase functions deploy cvn-claim-task cvn-complete-task cvn-fail-task cvn-status --use-api --project-ref ukqkkgzimhtjhlnmlyao
```
**Output:**
```text
Deploying Function: cvn-claim-task
Uploading asset (cvn-claim-task): supabase/functions/cvn-claim-task/index.ts
Uploading asset (cvn-claim-task): supabase/functions/_shared/broker_auth.ts
Deploying Function: cvn-complete-task
Uploading asset (cvn-complete-task): supabase/functions/cvn-complete-task/index.ts
Uploading asset (cvn-complete-task): supabase/functions/_shared/broker_auth.ts
Deploying Function: cvn-fail-task
Uploading asset (cvn-fail-task): supabase/functions/cvn-fail-task/index.ts
Uploading asset (cvn-fail-task): supabase/functions/_shared/broker_auth.ts
Deploying Function: cvn-status
Uploading asset (cvn-status): supabase/functions/cvn-status/index.ts
Uploading asset (cvn-status): supabase/functions/_shared/broker_auth.ts
{"project_ref":"ukqkkgzimhtjhlnmlyao","functions":["cvn-claim-task","cvn-complete-task","cvn-fail-task","cvn-status"],"dashboard_url":"https://supabase.com/dashboard/project/ukqkkgzimhtjhlnmlyao/functions","message":"Deployed Functions."}
```

---

## 4. Test Verification Results

All tests were executed against the live staging environment from the clean commit state.

### 4.1. Collected pytest Node IDs
```text
tests/integration/test_worker_identities.py::test_worker_identities
tests/integration/test_worker_identities.py::test_credential_disable_rotation
tests/integration/test_supabase_broker_extensions.py::test_broker_extensions
```

### 4.2. Existing 97-Test Regression Suite
```bash
.venv\Scripts\python -m pytest tests/unit tests/integration/test_openclaw_adapter_fake_gateway.py tests/integration/test_supabase_broker_milestone_2.py tests/integration/test_supabase_broker_extensions.py -v -rs
```

**Unedited Test Output:**
```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.1.0, pluggy-1.6.0
PySide6 6.11.1 -- Qt runtime 6.11.1 -- Qt compiled 6.11.1
rootdir: C:\Users\dsuth\Documents\Code Projects\Classroom voice notes
configfile: pyproject.toml
plugins: anyio-4.13.0, asyncio-1.4.0, qt-4.5.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 97 items

tests\unit\test_audio_worker.py .                                        [  1%]
tests\unit\test_broker_worker_routing.py .....                           [  6%]
tests\unit\test_commands.py ..                                           [  8%]
tests\unit\test_controller.py .....                                      [ 13%]
tests\unit\test_daily_summary.py .                                       [ 14%]
tests\unit\test_downloader.py ..                                         [ 16%]
tests\unit\test_external_agent_dispatcher.py ...                         [ 19%]
tests\unit\test_external_outbox.py .....                                 [ 24%]
tests\unit\test_hmac_signer.py .                                         [ 25%]
tests\unit\test_keyring_store.py ....                                    [ 29%]
tests\unit\test_main_window.py .....                                     [ 35%]
tests\unit\test_note_templates.py ..                                     [ 37%]
tests\unit\test_obsidian_writer.py ..                                    [ 39%]
tests\unit\test_openclaw_adapter.py ...................                  [ 58%]
tests\unit\test_payload_builder.py ...                                   [ 61%]
tests\unit\test_policy_gate_hardened.py ..........                       [ 72%]
tests\unit\test_recording_indicator.py ..                                [ 74%]
tests\unit\test_reminders.py ..                                          [ 76%]
tests\unit\test_review_queue.py ...                                      [ 79%]
tests\unit\test_run.py .                                                 [ 80%]
tests\unit\test_settings.py .....                                        [ 85%]
tests\unit\test_student_index.py .                                       [ 86%]
tests\unit\test_student_registry.py .                                    [ 87%]
tests\unit\test_telegram_dispatcher.py ....                              [ 91%]
tests\unit\test_wakeword.py ...                                          [ 94%]
tests\integration\test_openclaw_adapter_fake_gateway.py ...              [ 97%]
tests\integration\test_supabase_broker_milestone_2.py .                  [ 98%]
tests\integration\test_supabase_broker_extensions.py .                   [100%]

======================= 97 passed in 109.68s (0:01:49) ========================
```

### 4.3. Worker Identity & Credential Disable/Rotation Suite
```bash
.venv\Scripts\python -m pytest tests/integration/test_worker_identities.py -v -rs
```

**Unedited Test Output:**
```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.1.0, pluggy-1.6.0
PySide6 6.11.1 -- Qt runtime 6.11.1 -- Qt compiled 6.11.1
rootdir: C:\Users\dsuth\Documents\Code Projects\Classroom voice notes
configfile: pyproject.toml
plugins: anyio-4.13.0, asyncio-1.4.0, qt-4.5.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 2 items

tests\integration\test_worker_identities.py ..                           [100%]

======================== 2 passed in 161.94s (0:02:41) ========================
```

---

## 5. Security & Verification Analysis

- **Timing-Safe Authentication:** Handled in a single-pass buffer read. Signature verification and timing-safe string comparison occur before JSON parsing to prevent DoS or parsing attacks on unauthenticated payloads.
- **Worker-ID Constraint Enforcement:** `cvn-claim-task`, `cvn-complete-task`, and `cvn-fail-task` strictly validate the `allowed_worker_ids` list. Both cross-worker impersonation scenarios were verified to return `403 Forbidden` and prevent task mutation.
- **Indistinguishable Probing Prevention:** `cvn-status` returns `403 Forbidden` with a generic `"unauthorized"` error if a task is absent or if a worker is unauthorized. No sensitive data fields (`payload`, `claim_token`, etc.) are returned in queries.
- **Credential Rotation Integrity:** 
  - Verified that unique temporary key ID `test-rotation-worker-01` was used during rotation tests.
  - Verified that permanent Windows and VPS entries remained active.
  - Verified that old credentials return `401` after rotation.
  - Verified that restoring baseline registry successfully cleans up the rotation key.
  - Verified that old rotated credentials return `401` after cleanup.
  - Verified that permanent credential completes a successful authenticated request after cleanup.
- **No Secret Leakage:** Pytest outputs assert that no bearer tokens, HMAC secrets, or raw registry JSON structures appear in stdout, stderr, or logs.

---

## 6. Migration State Summary

| Migration | Filename | Staging Status | Production Status |
|---|---|---|---|
| 001 | `001_cvn_init_schema.sql` | Applied | Applied |
| 002 | `002_cvn_processed_nonces.sql` | Applied | Applied |
| 003 | `003_cvn_milestone_2_extensions.sql` | Applied | Applied |
| 004 | `004_cvn_task_reaping.sql` | Applied | Applied |
| 005 | `005_cvn_task_cancel_fail_retry.sql` | Applied | Applied |
| 006 | `006_cvn_phase_2c_broker_extensions.sql` | Applied | Applied |
| 007 | `007_cvn_phase_2c1_auth_extensions.sql` | **Applied** | *Pending* (Blocked) |
