# Phase 2C Independent Code Review Report

This report documents the independent review findings for the Classroom Voice Notes (CVN) Phase 2C staging pull request (PR #1).

---

## 1. Authentication & Security
- **Bearer Token Verification:** Deno Edge Functions hash the bearer token using SHA-256 before comparing it using a timing-safe equality checker (`timingSafeEqual`). This mitigates timing attacks and length extension vulnerabilities.
- **HMAC Signatures:** Request integrity and authenticity are verified via HMAC-SHA-256 signatures over the payload (or GET canonical string) validated against the `x-cvn-signature` header.
- **Replay Protection:** Nonce tracking is stored in the `cvn_processed_nonces` table. Stale timestamps are rejected if their age exceeds 5 minutes (`STALE_TIMESTAMP_SECONDS = 300`). Duplicate nonces result in an immediate 401 response.
- **Registry Security:** Multi-worker configuration is loaded from a JSON registry environment variable `AGENT_BROKER_WORKER_CREDENTIALS` which has a size cap (10KB) and fails closed if any unexpected schema properties are defined.
- **Credentials Sanitisation:** All actual passwords, token values, HMAC keys, and secret values are stored inside the secure hosting vault and are never hardcoded or printed.

---

## 2. Database Migrations 004–007
- **004_cvn_claim_complete_fail_status.sql:** Implements stored procedures for task lifecycle management (claim, complete, fail). It includes row locking (`FOR UPDATE`) to serialize access and prevent race conditions.
- **005_cvn_reaper_jobs.sql:** Schedules a background database stale claim reaper to run automatically every 5 minutes using `pg_cron`.
- **006_cvn_phase_2c_broker_extensions.sql:** Introduces target-specific queues (`cvn_tasks_queue_openclaw` and `cvn_tasks_queue_hermes`) in PGMQ, dynamically routing tasks to their respective queues. Limits privacy classifications strictly to `non_sensitive`.
- **007_cvn_phase_2c1_auth_extensions.sql:** Restricts database task operations (completion, failure) using `p_allowed_targets` verification matching the worker's security profile.

---

## 3. Target Separation
- Target agents are separated into two distinct queues: `cvn_tasks_queue_openclaw` and `cvn_tasks_queue_hermes`.
- Workers cannot claim tasks belonging to other target agents. The edge functions and database functions strictly enforce the allowed targets defined for each worker credential key ID.

---

## 4. systemd Worker Hardening
- Runs under a dedicated unprivileged user (`cvn-worker`).
- Hardened with systemd sandboxing properties: `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`, `PrivateTmp=true`.
- Secrets are loaded using standard systemd encrypted credentials (`LoadCredentialEncrypted`) mapping files into the secure `%d` directory rather than environment variables, reducing exposure risk.
- Launches Python with `-u` (unbuffered stdout) for real-time journalctl visibility.
- Employs a pre-execution gateway check (`wait_for_gateway.py`) ensuring loopback constraints (SSRF mitigation) and token validation.

---

## 5. Privacy Boundaries
- Fails closed on any task submit with classification other than `non_sensitive`.
- Withholds the task's input payload from the status retrieval endpoint (`cvn-status`), verifying status requests only return metadata and summaries rather than sensitive operational payloads.

---

## 6. Scope & Security Statement
- **Production Isolation:** Production environment was NOT changed, accessed, or authorised. All reviewed components are restricted strictly to staging.
- **Data Protection:** No credentials, raw headers, tokens, HMAC values, or database passwords are included or printed.
