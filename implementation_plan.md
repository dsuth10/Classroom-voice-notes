# Implementation Plan - Phase 3: Production Deployment & Live Agent Operations

This plan details the steps required to promote the Classroom Voice Notes (CVN) Broker, OpenClaw VPS worker, and CVN Client Outbox Dispatcher from live staging to **Production**.

## User Review Required

> [!IMPORTANT]
> **Environment Isolation & Security**: Production credentials (HMAC Secret, Bearer Token) MUST be generated freshly using cryptographic random generation (`openssl rand -hex 32`) and stored securely in Windows Credential Manager and systemd encrypted credentials. Under no circumstances will staging credentials be reused in production.

> [!WARNING]
> **Production Database State**: Database migrations `001_cvn_broker_mvp.sql` through `005` will be applied directly to the production Supabase database. Ensure production database backup is confirmed before running schema migrations.

## Open Questions

> [!IMPORTANT]
> Please review and confirm the following design decisions before execution:

1. **Production Supabase Project ID**: Is the production Supabase project reference available for CLI linking and migration push?
2. **VPS Deployment Strategy**: Will the production worker run on a dedicated production host or as a separate isolated systemd unit (`cvn-worker-prod.service`) on the existing VPS?
3. **Acceptance Criteria**: Does the proposed synthetic production smoke test meet your criteria for final production sign-off?

---

## Proposed Changes

### Documentation & Planning

#### [MODIFY] [Phase3.md](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/Ideas/Phase3.md)
- Complete technical plan for Phase 3 production deployment, security gating, and validation sequence.

---

### Database & Edge Functions (Supabase)

#### [MODIFY] `supabase/migrations/`
- Apply existing frozen migrations `001` through `005` to production database:
  - `001_cvn_broker_mvp.sql`
  - `002_pgmq_schema_grants.sql`
  - `003_cvn_submit_task_security_definer.sql`
  - `004_...`
  - `005_...`

#### [MODIFY] `supabase/functions/`
- Deploy production Edge Functions:
  - `cvn-submit-task`
  - `cvn-claim-task`
  - `cvn-complete-task`
  - `cvn-fail-task`
  - `cvn-status`

---

### VPS Worker Service

#### [NEW] `deploy/vps/cvn-worker-prod.service`
- Systemd service unit for the production worker process with restrictive security sandboxing (`ProtectSystem=strict`, `NoNewPrivileges=true`).

---

### CVN Client App

#### [MODIFY] [settings.json](file:///c:/Users/dsuth/Documents/Code%20Projects/Classroom%20voice%20notes/settings.json)
- Configure production broker endpoint URLs and OS keychain credential references.

---

## Verification Plan

### Automated Tests
- `pytest tests/unit/` - Run full unit test suite ensuring 100% pass rate.
- `pytest tests/integration/` - Run outbox and dispatcher safe integration tests.
- `ruff check .` & `mypy app` - Code quality and type safety gates.

### Manual & Production Verification
- **Migration Check**: `supabase migration list` to verify all 5 migrations are applied on production.
- **Worker Health**: `systemctl status cvn-worker-prod` to confirm active polling state.
- **End-to-End Synthetic Smoke Run**: Dispatch a non-sensitive synthetic task via CVN client, verify broker receipt, VPS claim, OpenClaw execution, broker completion, and client note update.
