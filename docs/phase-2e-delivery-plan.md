# Phase 2E Delivery Plan

**Branch:** `feature/phase-2e-operational-hardening`  
**Base:** `main` at `4afd67d7ffed75a033c564b3860d9177274e65d2`  
**Environment:** Staging only  
**Production status:** Not authorised

This plan supersedes the unpublished post-Phase 2C roadmap commit `f37c2fb`
on the local `docs/phase-2c-closure` branch. That branch is retained for
history until normal repository cleanup; current execution status belongs in
this document.

## Objective

Complete the operational-hardening milestone with a fail-closed outbox,
clear environment separation, reliable status reconciliation, automated
quality gates, and a repeatable synthetic staging acceptance test.

No production deployment, production credential provisioning, public gateway
exposure, or real classroom data is included in this phase.

## Delivery sequence

### 1. Restore the quality baseline

Status: **Complete locally**

- [x] Require exact broker environment values.
- [x] Resolve Ruff findings.
- [x] Resolve strict mypy findings.
- [x] Run the complete unit-test suite.

Gate:

- Ruff passes.
- Mypy passes for `app`.
- All unit tests pass.

### 2. Close outbox correctness and security gaps

Status: **Complete locally**

- [x] Clear obsolete retry timestamps when a task is sent or reconciled.
- [x] Validate stored broker endpoints against the active environment.
- [x] Reject lookalike hosts, alternate ports, non-HTTPS URLs, queries, and fragments.
- [x] Apply seven-day retention before transmission retries.
- [x] Persist the selected target agent in the outbox.
- [x] Recover the target agent from legacy payloads during reconciliation.
- [x] Add regression tests for these transitions.

Gate:

- A stale or tampered endpoint cannot receive a signed request.
- A successful task cannot retain a retry schedule.
- An expired task moves to dead letter before transmission.
- Reconciled notes retain the authoritative target agent.

### 3. Complete regression coverage

Status: **Complete locally**

- [x] Test the background outbox worker success and failure paths.
- [x] Test settings counter refresh after worker completion.
- [x] Test selective retry and archive confirmation in the outbox dialog.
- [x] Test shutdown while an outbox worker is active.
- [x] Test status reconciliation for both Hermes and OpenClaw tasks.
- [x] Run the full safe integration suite.

Gate:

- Thread lifecycle and UI actions are deterministic.
- No dead-letter record changes without selection and confirmation.
- Safe integration tests pass without live credentials.

### 4. Align documentation and repository metadata

Status: **Complete locally**

- [x] Update the README architecture to show the Supabase/OpenClaw broker path.
- [x] Change documented Python support from 3.9+ to 3.11+.
- [x] Correct the audit-log location.
- [x] Document outbox recovery and environment selection.
- [x] Add the referenced MIT licence file or correct the licence claim.
- [x] Reconcile the unpublished `docs/phase-2c-closure` roadmap commit.

Gate:

- Setup and operating instructions match the current implementation.
- No documentation implies that production is authorised.

### 5. Add automated pull-request gates

Status: **Complete locally; awaiting the first GitHub Actions run**

- [x] Run unit and safe integration tests in GitHub Actions.
- [x] Run Ruff and mypy.
- [x] Add secret scanning.
- [x] Reject tracked `scratch/` and `supabase/.temp/` files.
- [x] Verify required repository documentation.

Gate:

- A pull request cannot pass when tests, typing, linting, secret scanning,
  or protected-path checks fail.

### 6. Staging acceptance and pull request

Status: **Pending**

- [ ] Run a deterministic synthetic application-originated task.
- [ ] Verify one enqueue, one claim, one execution, and one completion.
- [ ] Verify the signed status response and Obsidian note update.
- [ ] Confirm no raw transcript, audio path, credential, or classroom data appears remotely.
- [ ] Capture sanitised evidence.
- [ ] Perform an independent review.
- [ ] Open the Phase 2E pull request.

Gate:

- Full local checks pass.
- Live synthetic staging acceptance passes.
- Review has no unresolved blockers.
- Production remains unchanged.

## Suggested commit sequence

1. `fix: restore strict phase 2e quality gates`
2. `fix: harden outbox endpoint and retry state handling`
3. `test: cover outbox worker and management lifecycle`
4. `docs: align phase 2e architecture and operations`
5. `ci: add phase 2e pull-request quality gates`

Commits should remain separate until review so correctness, tests,
documentation, and CI can be assessed independently.

## Definition of done

Phase 2E is complete only when:

- local and CI quality gates pass;
- ordinary retry never revives dead-letter work;
- every outbound or status endpoint is environment-bound and fail-closed;
- task state and agent identity remain consistent in SQLite and Obsidian;
- the safe integration suite passes;
- the synthetic staging acceptance task completes exactly once;
- review has no unresolved security or operational blockers; and
- no production change has occurred.
