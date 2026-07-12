# Phase 2C.2 Developer Investigation and Implementation Instructions

**Project:** Classroom Voice Notes (CVN) Broker  
**Audience:** Developer with no prior knowledge of the project  
**Environment in scope:** Supabase staging and the OpenClaw VPS only  
**Staging project reference:** `ukqkkgzimhtjhlnmlyao`  
**Current feature branch:** `feature/phase-2c2-vps-staging-worker`  
**Reported candidate commit:** `5f7a7c190a28a2989f0defa2419cf3b981bb37b8`  
**Production changes:** Not authorised  

---

## 1. Purpose of this document

This document explains the system, the work already completed, the unresolved problem, and the exact investigation and implementation steps required to progress Phase 2C.2 safely.

Do not assume that prior summaries are accurate merely because they report passing tests or a clean Git state. Inspect the source repository, the deployed staging configuration, and the VPS directly. Record evidence for every conclusion.

The immediate objective is to provision a dedicated CVN worker on the VPS and prove one synthetic task can travel through the complete staging workflow:

1. A test client submits a task to the staging broker.
2. The VPS worker authenticates with its dedicated identity.
3. The worker claims only a task targeted to `openclaw`.
4. The worker sends the instruction to the loopback OpenClaw gateway.
5. OpenClaw executes it and returns the result.
6. The worker completes or fails the broker task.
7. The client retrieves a sanitised status response.

No real classroom data may be used.

---

## 2. System overview

### 2.1 Components

| Component | Location | Responsibility |
|---|---|---|
| CVN Windows client | Douglas's Windows machine | Creates voice-note tasks and submits approved external-agent work |
| Supabase staging broker | Project `ukqkkgzimhtjhlnmlyao` | Stores tasks, authenticates clients/workers, controls claims, completion, failure and status |
| Windows/Hermes worker | Windows/local environment | Processes tasks targeted to `hermes` |
| VPS broker worker | OpenClaw VPS | Polls and processes tasks targeted only to `openclaw` |
| OpenClaw gateway | VPS loopback port `18789` | Executes an instruction received from the local VPS worker |
| Antigravity | Windows development environment | Builds, deploys, configures and verifies the system |

### 2.2 Trust boundary

The VPS broker worker—not OpenClaw itself—owns the broker protocol. The worker holds the Supabase worker identity, signs requests, claims tasks, calls the local gateway, and reports completion or failure.

OpenClaw must not:

- possess Supabase registry-administration credentials;
- modify the Supabase database or Edge Functions;
- rotate its own broker identity;
- claim tasks directly unless the approved design explicitly changes;
- configure systemd, Git or firewall rules;
- expose its gateway publicly.

### 2.3 Phase 2C.1 baseline

Phase 2C.1 introduced separate worker identities and was signed off in staging. The reported baseline includes:

- migration `007_cvn_phase_2c1_auth_extensions.sql` applied to staging;
- Edge Functions `cvn-claim-task`, `cvn-complete-task`, `cvn-fail-task`, and `cvn-status` deployed;
- explicit `allowed_targets` and `allowed_worker_ids` enforcement;
- cross-worker impersonation rejection;
- credential disablement and rotation tests;
- legacy authentication restricted to Hermes;
- sanitised status results;
- staging credential registry restored after lifecycle testing.

Verify this baseline rather than modifying it unnecessarily.

---

## 3. Current Phase 2C.2 implementation claims

The current branch is reported to contain:

- fail-closed worker configuration checks;
- staging-environment validation;
- target-aware preservation of Windows/Hermes behaviour;
- systemd encrypted-credential file loading;
- strict loopback/Unix-socket validation for the OpenClaw gateway;
- a hardened systemd service template;
- a VPS diagnostic script;
- a synthetic staging-task submission harness;
- integration-test collection that skips cleanly when credentials are unavailable.

The most recent reported local result is:

```text
109 collected
104 passed
5 skipped
```

The five skips are live/staging tests and must execute during Phase 2C.2. A skipped test is not a pass.

---

## 4. The unresolved problem

The provided systemd template was originally designed to depend on an `openclaw.service`. Direct VPS inspection established that no such systemd unit exists.

Known VPS facts:

| Item | Observed value |
|---|---|
| Operating system | Ubuntu 24.04.4 LTS |
| Kernel | Linux 6.8.0-110-generic x64 |
| systemd | 255.4 |
| Python | 3.12.3 |
| OpenClaw process | Root-owned Node process running `openclaw/dist/index.js gateway --port 18789` |
| Gateway IPv4 binding | `127.0.0.1:18789` |
| Gateway IPv6 binding | `[::1]:18789` |
| `openclaw.service` | Does not exist |
| Other relevant service | `nerve.service`, active and running |
| Clock | Synchronised; NTP active |
| Supabase connectivity | DNS and TLS succeeded; unauthenticated request returned HTTP 400 |
| Root filesystem | 145 GB total, 92 GB available |
| Overall systemd state | `degraded` |

Unknown facts that block safe deployment:

1. What launched the OpenClaw gateway process?
2. Is it a child of `nerve.service`, a user service, a shell session, a container, cron, or another supervisor?
3. What restarts it after a crash?
4. What starts it after a VPS reboot?
5. Which systemd units cause the degraded state?
6. Is the degraded state related to OpenClaw, networking or the proposed CVN worker?
7. Does the current systemd template still reference the nonexistent `openclaw.service`?
8. Does the live task harness require `CVN_BROKER_ENV` to equal exactly `staging`, or does it merely reject the literal value `production`?

Do not provision or start the CVN service until these questions are answered.

---

## 5. Authorisation and safety boundaries

### 5.1 Authorised

- Read the repository and VPS configuration.
- Run non-destructive discovery commands.
- Create changes on `feature/phase-2c2-vps-staging-worker`.
- Run local tests.
- Update staging-only configuration after all preflight gates pass.
- Install a staging CVN worker after its environment-specific service unit is reviewed.
- Submit synthetic staging tasks.

### 5.2 Not authorised

- Merge to `main`.
- Deploy to production.
- Use student, teacher, email or classroom data.
- Remove the legacy Hermes path.
- Expose the OpenClaw gateway on a network interface.
- Reconfigure the unrelated public listeners on ports `3080` or `45680` as part of this phase.
- Replace or redesign the existing OpenClaw launcher without separate approval.
- Roll back migration 007.
- Print, commit or report secrets.

### 5.3 Immediate stop conditions

Stop and report if:

- any resolved broker URL points outside staging;
- gateway port `18789` is not loopback-only;
- a credential appears in output or Git;
- the permanent Windows registry entry cannot be preserved;
- the OpenClaw gateway has no reliable launch/recovery mechanism and the proposed worker depends on it;
- the VPS worker can target `hermes`;
- the Windows worker can claim `openclaw` tasks;
- a migration discrepancy is discovered;
- any security integration test fails;
- a task remains orphaned or executes more than once.

---

## 6. Repository investigation

Perform this work on the Windows development machine in the actual CVN repository.

### 6.1 Confirm repository identity and state

```powershell
git remote -v
git branch --show-current
git rev-parse HEAD
git status --short
git log --oneline --decorate -10
git diff 4d5274e0d7c0409a2b535d506935cc2352136d81..HEAD --stat
```

Expected branch:

```text
feature/phase-2c2-vps-staging-worker
```

Reported commit:

```text
5f7a7c190a28a2989f0defa2419cf3b981bb37b8
```

If the checked-out commit differs, establish why before continuing.

### 6.2 Review all Phase 2C.2 changes

```powershell
git diff 4d5274e0d7c0409a2b535d506935cc2352136d81..HEAD -- `
  app/worker/broker_worker.py `
  tests/unit/test_broker_worker_routing.py `
  tests/integration `
  deploy `
  scripts/submit_test_task_openclaw.py
```

Inspect at least:

- `app/worker/broker_worker.py`
- `app/worker/openclaw_adapter.py`, or the actual gateway adapter
- `deploy/cvn-openclaw-staging-worker.service`
- `deploy/diagnose_worker.py`
- `deploy/README.md`
- `scripts/submit_test_task_openclaw.py`
- `tests/unit/test_broker_worker_routing.py`
- `tests/integration/test_openclaw_staging.py`
- `tests/integration/test_worker_identities.py`
- `tests/integration/test_supabase_broker_milestone_2.py`
- `tests/integration/test_supabase_broker_extensions.py`

### 6.3 Verify credential-file loading

Confirm the worker reads:

```text
AGENT_BROKER_BEARER_TOKEN_FILE
AGENT_BROKER_HMAC_SECRET_FILE
OPENCLAW_GATEWAY_TOKEN_FILE
```

Required behaviour:

- For `openclaw`, all three files must exist, be readable and be non-empty.
- For `hermes`, OpenClaw gateway configuration and gateway token must not be required.
- File contents must be stripped of trailing newline safely.
- Files should have a reasonable maximum size to avoid accidentally reading an inappropriate file.
- Errors must identify the missing configuration item without printing its value.
- Ordinary secret environment variables must not silently override file credentials unless an explicitly documented compatibility rule requires it.
- Secret values must not appear in `repr`, logging, exceptions or diagnostics.

Add tests for missing, unreadable, empty and oversized credential files if they do not exist.

### 6.4 Verify gateway URL validation

Allowed endpoints should be limited to:

```text
http://127.0.0.1:<approved-port>
http://localhost:<approved-port>
http://[::1]:<approved-port>
unix://...
http+unix://...
```

For the staging VPS, strongly prefer the exact endpoint:

```text
http://127.0.0.1:18789
```

Reject:

- `0.0.0.0`;
- `[::]`;
- LAN, VPN and public IP addresses;
- arbitrary hostnames;
- URLs containing `username:password@host`;
- scheme-relative URLs;
- unexpected schemes;
- malformed IPv6 forms;
- redirect-based attempts to reach a remote host.

The HTTP client should not automatically follow a redirect from loopback to a non-loopback destination.

### 6.5 Verify staging-only harness controls

The submission harness must use positive allowlisting:

```python
if os.environ.get("CVN_BROKER_ENV") != "staging":
    raise RuntimeError("Live test harness requires CVN_BROKER_ENV=staging")
```

It must also verify every resolved broker URL contains:

```text
ukqkkgzimhtjhlnmlyao
```

It must fail for missing, empty, `prod`, `production`, `development`, misspelt or mixed-case unexpected environment values.

The synthetic payload must contain no private data and should request only:

```text
CVN_OPENCLAW_STAGING_OK
```

### 6.6 Inspect the systemd template

Search for invalid dependencies:

```powershell
rg -n "openclaw\.service|Requires=|After=|LoadCredential|CREDENTIALS_DIRECTORY|%d|ExecStartPre|CVN_BROKER_ENV" deploy app
```

Do not retain `Requires=openclaw.service` or `After=openclaw.service` because the VPS has no such unit.

Do not choose a replacement dependency until the VPS process hierarchy is understood.

---

## 7. VPS investigation

Run these commands read-only. Redact unexpected secret-bearing command arguments. Do not inspect `/proc/*/environ`.

### 7.1 Identify failed units

```bash
systemctl --failed --no-pager
systemctl is-system-running
```

For each failed unit:

```bash
systemctl show UNIT_NAME \
  --property=LoadState,ActiveState,SubState,Result,User,Group,FragmentPath

journalctl -u UNIT_NAME -n 100 --no-pager
```

Redact secrets if a unit logged any. Determine whether the failure relates to OpenClaw, Nerve, networking or CVN.

### 7.2 Trace the OpenClaw gateway process

Do not rely permanently on PID `3483682`; rediscover it:

```bash
pgrep -af 'openclaw.*gateway|openclaw/dist/index.js.*gateway'
```

For the selected gateway PID:

```bash
gateway_pid="<PID>"
ps -o pid,ppid,user,lstart,etimes,cmd -p "$gateway_pid"

gateway_ppid="$(ps -o ppid= -p "$gateway_pid" | tr -d ' ')"
ps -o pid,ppid,user,lstart,etimes,cmd -p "$gateway_ppid"

cat "/proc/$gateway_pid/cgroup"
pstree -aps "$gateway_pid"
```

Do not print process environments.

Interpretation:

- A cgroup path containing a named `.service` may identify the supervisor.
- A parent shell, SSH session, `screen`, or `tmux` session suggests weak or manual supervision.
- A container cgroup requires inspection of the corresponding container runtime.
- A parent belonging to `nerve.service` may mean Nerve launches the gateway, but confirm restart and boot behaviour rather than assuming it.

### 7.3 Inspect Nerve without exposing configuration secrets

```bash
systemctl status nerve.service --no-pager

systemctl show nerve.service \
  --property=LoadState,ActiveState,SubState,User,Group,MainPID,FragmentPath,Restart,RestartUSec

systemctl cat nerve.service
```

Before placing `systemctl cat` output in a report, redact any inline credentials. Do not print referenced environment files.

Answer:

1. Is the gateway in the Nerve service cgroup?
2. Does Nerve start at boot?
3. Does Nerve use `Restart=`?
4. If the gateway dies independently, does Nerve notice and recreate it?

Do not test a crash on the live process yet.

### 7.4 Search for other launch mechanisms

```bash
systemctl list-unit-files --type=service | grep -Ei 'openclaw|nerve|gateway'
systemctl list-units --type=service --all | grep -Ei 'openclaw|nerve|gateway'

systemctl --user list-unit-files --type=service 2>/dev/null | grep -Ei 'openclaw|nerve|gateway'
systemctl --user list-units --type=service --all 2>/dev/null | grep -Ei 'openclaw|nerve|gateway'

crontab -l 2>/dev/null
sudo crontab -l 2>/dev/null

command -v supervisorctl >/dev/null && supervisorctl status
command -v pm2 >/dev/null && pm2 list
command -v docker >/dev/null && docker ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}'
command -v podman >/dev/null && podman ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}'
```

Do not print crontab lines that contain secrets; redact them while retaining the launch mechanism.

### 7.5 Confirm gateway binding again

```bash
sudo ss -ltnp | grep ':18789'
```

Accept only `127.0.0.1` and `[::1]` bindings.

### 7.6 Confirm encrypted-credential capability

```bash
systemd-creds --version
systemd-creds has-tpm2
```

No TPM is expected. Host-key encryption may be acceptable for this staging VPS if `systemd-creds encrypt` and service loading are verified. Do not place plaintext secret values in command arguments.

Use a disposable non-secret test string to validate the mechanism before provisioning real credentials.

### 7.7 Produce a VPS discovery conclusion

The developer must state explicitly:

- gateway launch mechanism;
- gateway boot behaviour;
- gateway crash-recovery behaviour;
- service/cgroup owner;
- reason for degraded systemd state;
- whether that reason blocks CVN deployment;
- safe dependency/readiness strategy for the CVN worker.

---

## 8. Choose the service integration design

Use the evidence to select exactly one design.

### Design A: Existing reliable supervisor identified

If a real systemd service reliably owns and restarts the gateway:

- use `After=<real-unit>`;
- use `Wants=<real-unit>` or `Requires=<real-unit>` only if failure coupling is desirable and understood;
- retain an `ExecStartPre` readiness check against loopback;
- do not use `openclaw.service` as a fictional alias.

### Design B: Nerve starts the gateway but does not supervise it reliably

If Nerve only launches the gateway once:

- do not claim the gateway is supervised;
- make the worker use bounded retries and fail safely while the gateway is unavailable;
- consider `After=nerve.service` plus a readiness check;
- document that a gateway crash still requires separate remediation;
- obtain approval before altering the OpenClaw/Nerve installation.

### Design C: Gateway is manually launched or unsupervised

Do not enable the CVN worker for continuous operation. Prepare a separate proposal for gateway supervision containing:

- proposed service owner;
- exact executable and working directory;
- safe credential/configuration loading;
- restart policy;
- boot policy;
- compatibility with Nerve and plugins;
- rollback plan.

Do not implement that redesign implicitly as part of CVN Phase 2C.2.

---

## 9. Build the environment-specific worker unit

After selecting a design, update `deploy/cvn-openclaw-staging-worker.service`.

Minimum properties:

```ini
[Unit]
Description=CVN OpenClaw Staging Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cvn-worker
Group=cvn-worker
WorkingDirectory=/opt/cvn-worker

Environment=CVN_BROKER_ENV=staging
Environment=CVN_WORKER_ID=vps-worker-id-staging
Environment=AGENT_BROKER_KEY_ID=vps-worker-staging
Environment=CVN_TARGET_AGENT=openclaw
Environment=OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789

LoadCredentialEncrypted=cvn-broker-bearer:/etc/cvn/credentials/broker-bearer
LoadCredentialEncrypted=cvn-broker-hmac:/etc/cvn/credentials/broker-hmac
LoadCredentialEncrypted=openclaw-gateway-token:/etc/cvn/credentials/openclaw-gateway-token

Environment=AGENT_BROKER_BEARER_TOKEN_FILE=%d/cvn-broker-bearer
Environment=AGENT_BROKER_HMAC_SECRET_FILE=%d/cvn-broker-hmac
Environment=OPENCLAW_GATEWAY_TOKEN_FILE=%d/openclaw-gateway-token

ExecStartPre=/opt/cvn-worker/.venv/bin/python /opt/cvn-worker/deploy/diagnose_worker.py --service-preflight
ExecStart=/opt/cvn-worker/.venv/bin/python -m app.worker.broker_worker

Restart=on-failure
RestartSec=10s
TimeoutStopSec=30s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
```

This is a design reference, not a drop-in unit. Add the real gateway dependency identified during discovery. Add `ReadWritePaths=` only for directories the worker genuinely needs.

Validate on the VPS:

```bash
systemd-analyze verify /path/to/cvn-openclaw-staging-worker.service
```

Resolve every warning relevant to correctness or security.

---

## 10. Tests required before VPS provisioning

### 10.1 Local tests

Run from the Windows repository:

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy app
.venv\Scripts\python -m pytest -v -rs
```

Report exact passed, failed, skipped and deselected totals.

Add or confirm tests for:

- staging environment must equal exactly `staging`;
- wrong/missing environment rejected;
- wrong Supabase project rejected;
- missing/empty/unreadable credential file rejected;
- Hermes does not require OpenClaw token;
- non-loopback gateway rejected;
- embedded URL credentials rejected;
- redirects to remote endpoints rejected or not followed;
- target pinned to `openclaw` for the VPS configuration;
- synthetic harness cannot accept arbitrary payloads by default.

### 10.2 Freeze a new candidate only if changes are required

```powershell
git diff --check
git status --short
git add <reviewed-files>
git commit -m "Harden VPS staging worker preflight and service integration"
git push -u origin feature/phase-2c2-vps-staging-worker
git rev-parse HEAD
git status --short
```

Do not create meaningless commits merely to change the hash. Each commit must correspond to reviewed changes.

---

## 11. VPS provisioning procedure

Proceed only after the discovery and code-review gates pass.

### 11.1 Service account and directories

Use a non-root service account such as `cvn-worker`. Reuse an appropriate existing account only if its permissions are well understood.

Recommended paths:

```text
/opt/cvn-worker
/etc/cvn/credentials
/var/lib/cvn-worker
```

Application code should not be writable by the service account. Runtime state should be writable only where necessary.

### 11.2 Deploy an exact commit

On the VPS:

```bash
cd /opt/cvn-worker
git fetch --all --prune
git checkout --detach <APPROVED_COMMIT>
git rev-parse HEAD
git status --short
```

Do not deploy a moving branch tip.

### 11.3 Install dependencies

Use the repository's authoritative lockfile/install process. If no process is documented, stop and establish one rather than installing unpinned dependencies casually.

### 11.4 Provision staging credentials

Identity:

```text
Key ID: vps-worker-staging
Worker ID: vps-worker-id-staging
Allowed target: openclaw
```

Generate fresh staging-only bearer, HMAC and gateway credentials. Preserve the permanent Windows/Hermes registry entry.

Rules:

- never place plaintext secrets in command arguments;
- never commit plaintext or encrypted credential artefacts;
- use a restricted memory-backed temporary file where practical;
- encrypt with `systemd-creds` for the VPS;
- remove plaintext immediately;
- verify file ownership and permissions;
- do not print the secret to validate it.

### 11.5 Run diagnostics under the service credential context

Because `%d` is populated by systemd, a direct shell invocation may not represent the real service environment. Prefer a temporary diagnostic unit or run the installed service's `ExecStartPre` without starting continuous polling.

The diagnostic result should confirm only:

- required configuration is present;
- staging project is selected;
- credential files are present/readable;
- gateway is loopback-only and reachable;
- DNS/TLS connectivity works;
- clock is synchronised.

It must not print credential values.

### 11.6 Start but do not enable

```bash
sudo systemctl daemon-reload
sudo systemctl start cvn-openclaw-staging-worker.service
sudo systemctl status cvn-openclaw-staging-worker.service --no-pager
sudo journalctl -u cvn-openclaw-staging-worker.service --since '10 minutes ago' --no-pager
```

Do not enable at boot until live testing passes.

---

## 12. Live staging verification

### 12.1 Negative checks first

| Scenario | Expected result |
|---|---:|
| VPS credential with Windows worker ID | `403` |
| VPS credential targeting Hermes | `403` |
| Invalid bearer | `401` |
| Invalid HMAC signature | `401` |
| Replayed nonce | `401` |
| Valid VPS identity with no available task | Authorised empty/no-task response |

Confirm no negative test leaves a task claimed.

### 12.2 Successful task

Submit a unique synthetic task requesting exactly:

```text
CVN_OPENCLAW_STAGING_OK
```

Record:

- approved Git commit;
- staging project reference;
- correlation ID;
- task ID;
- submission, claim, execution and completion timestamps;
- worker ID and target;
- sanitised final status.

Acceptance criteria:

1. Submission succeeds.
2. Only the VPS/OpenClaw worker can claim it.
3. OpenClaw executes it exactly once.
4. The worker completes the task.
5. Status returns the expected marker.
6. Status excludes payload, claim token, queue ID and secrets.
7. Duplicate completion is rejected.
8. Replayed authentication is rejected.
9. Worker resumes healthy polling.

### 12.3 Execute all previously skipped tests

Run with staging credentials supplied securely:

```powershell
.venv\Scripts\python -m pytest `
  tests/integration/test_supabase_broker_extensions.py `
  tests/integration/test_supabase_broker_milestone_2.py `
  tests/integration/test_worker_identities.py `
  -v -rs
```

Run the live gateway test where loopback access is available:

```bash
RUN_LIVE_OPENCLAW_TESTS=true \
python -m pytest \
  tests/integration/test_openclaw_staging.py::test_live_gateway_echo \
  -v -rs
```

Do not expose port `18789` to make a remote test convenient. Run the test on the VPS or through a secure method that preserves loopback binding.

All five formerly skipped tests must pass.

### 12.4 Failure and recovery tests

Using synthetic tasks, verify:

- gateway error produces `cvn-fail-task`;
- wrong worker cannot complete the task;
- duplicate completion is rejected;
- worker interruption produces documented lease/reaper behaviour;
- restart returns the worker to healthy polling;
- no task remains indefinitely claimed.

Do not kill the existing OpenClaw gateway merely to simulate failure if a fake adapter or controlled invalid request can test the path.

---

## 13. Rollback

If a security, identity or task-state check fails:

```bash
sudo systemctl disable --now cvn-openclaw-staging-worker.service
```

Then:

1. Disable `vps-worker-staging` in the staging registry.
2. Confirm its requests return `401`.
3. Preserve sanitised diagnostics.
4. Leave migration 007 and the verified Phase 2C.1 functions in place.
5. Do not alter the Windows identity unless directly affected.
6. Do not improvise a database rollback.
7. Do not redesign the OpenClaw supervisor without approval.

---

## 14. Required evidence report

Create:

```text
Phase_2C2_VPS_Provisioning_and_Live_Staging_Report.md
```

Include:

- repository branch, commit and clean status;
- reviewed diff summary;
- VPS operating system, Python and systemd versions;
- failed-unit investigation;
- gateway process tree, cgroup and actual supervisor;
- gateway boot and crash-recovery conclusion;
- final environment-specific service unit;
- `systemd-analyze verify` result;
- credential-provisioning method without values;
- diagnostic results;
- exact test commands and totals;
- all formerly skipped tests executing and passing;
- negative authorisation results;
- successful live-task timeline;
- failure/recovery results;
- sanitised relevant logs;
- confirmation that no real classroom data was used;
- confirmation that nothing was merged or deployed to production;
- one final result: `PASS`, `FAIL`, or `BLOCKED`.

Replace sensitive values with `[REDACTED]`. Do not commit raw logs containing secrets.

---

## 15. Definition of done

Phase 2C.2 is complete only when:

- the real OpenClaw gateway lifecycle is understood;
- the degraded systemd state is explained;
- the CVN unit references only real dependencies;
- encrypted credentials load under systemd;
- the worker runs as a non-root account;
- the gateway remains loopback-only;
- staging and target checks fail closed;
- Windows/Hermes remains compatible;
- all local and staging tests pass;
- one synthetic task completes end to end exactly once;
- failure and lease-recovery paths behave correctly;
- no credentials leak;
- no task remains orphaned;
- a clean, pushed commit exactly matches the VPS deployment;
- the final report is complete;
- no merge or production deployment has occurred.

---

## 16. First action for the assigned developer

Do not begin by writing code. Begin by producing a short discovery addendum containing:

1. the actual repository HEAD and diff from the Phase 2C.1 baseline;
2. the relevant current systemd template;
3. proof of the test harness's exact staging allowlist;
4. `systemctl --failed` results;
5. the OpenClaw gateway process tree and cgroup;
6. the relationship, if any, between the gateway and `nerve.service`;
7. the recommended service-integration design: A, B or C from Section 8.

Only after that addendum is reviewed should the developer modify code, provision credentials or install the VPS worker.
