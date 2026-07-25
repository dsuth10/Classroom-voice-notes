# OpenClaw Staging Worker Runbook

This runbook provisions and verifies the Classroom Voice Notes OpenClaw worker
in the Supabase staging environment.

It does not authorise production deployment, public gateway exposure,
production credentials or real classroom data.

## Current baseline

- Repository: `dsuth10/Classroom-voice-notes`
- Verified Phase 2C merge: `4afd67d7ffed75a033c564b3860d9177274e65d2`
- Verified tag: `cvn-broker-phase-2c-staging-complete`
- Service unit: `cvn-openclaw-staging-worker.service`
- Service account: `cvn-worker`
- Checkout: `/opt/cvn-worker`
- Broker environment: `staging`
- Target agent: `openclaw`
- Gateway: loopback on port `18789`

Phase 2E code must not be deployed merely because it exists on a feature
branch. Deploy it only after its pull request, quality gates, review and
synthetic staging acceptance have passed.

## Safety rules

1. Use only the staging Supabase project `ukqkkgzimhtjhlnmlyao`.
2. Use only the registered staging key ID, bearer/HMAC pair and worker ID.
3. Keep the OpenClaw gateway on `127.0.0.1` and `::1`.
4. Never place credentials in Git, shell history, arguments, logs or screenshots.
5. Use synthetic, non-sensitive tasks only.
6. Verify the exact Git commit before starting the service.
7. Stop on any environment, identity, endpoint or gateway ambiguity.

See [Environment and Credential Operations](../docs/operations/environment-and-credentials.md)
for the desktop environment and credential boundary.

## 1. Create the service account and layout

Run as an authorised VPS administrator:

```bash
sudo useradd \
  --system \
  --home /var/lib/cvn-worker \
  --create-home \
  --shell /usr/sbin/nologin \
  cvn-worker

sudo mkdir -p /opt/cvn-worker
sudo chown -R "$USER":cvn-worker /opt/cvn-worker
sudo chmod -R 750 /opt/cvn-worker

sudo mkdir -p /etc/cvn/credentials
sudo chown -R root:cvn-worker /etc/cvn/credentials
sudo chmod 550 /etc/cvn/credentials
```

If the account already exists, verify it rather than recreating it:

```bash
getent passwd cvn-worker
id cvn-worker
```

## 2. Align the checkout

Clone the repository if required, then align to the reviewed deployment commit:

```bash
cd /opt/cvn-worker
git fetch --tags origin
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
```

The working tree must be clean. Compare the reported commit with the exact
commit approved for this deployment.

For the Phase 2C staging baseline:

```bash
git rev-parse cvn-broker-phase-2c-staging-complete
```

Expected:

```text
4afd67d7ffed75a033c564b3860d9177274e65d2
```

Do not merge or retain obsolete pre-history-rewrite feature branches on the
VPS.

## 3. Install the Python environment

```bash
cd /opt/cvn-worker
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -c "from app.destinations.openclaw_adapter import OpenClawAdapter"
```

The worker requires Python 3.11 or newer.

## 4. Provision encrypted credentials

The checked-in service unit expects three systemd encrypted credential files:

```text
/etc/cvn/credentials/cvn-broker-bearer
/etc/cvn/credentials/cvn-broker-hmac
/etc/cvn/credentials/openclaw-gateway-token
```

Provision these through the approved password-vault and `systemd-creds`
workflow. This repository intentionally does not include commands that place
secret values on a shell command line.

Required properties:

- the files contain encrypted systemd credentials, not plaintext;
- owner is `root`;
- group is `cvn-worker`;
- the directory is not writable by `cvn-worker`;
- staging values are distinct from all production values; and
- values are never printed during verification.

Verify only metadata:

```bash
sudo stat \
  /etc/cvn/credentials/cvn-broker-bearer \
  /etc/cvn/credentials/cvn-broker-hmac \
  /etc/cvn/credentials/openclaw-gateway-token
```

If encrypted credentials are unavailable on the host, stop and obtain a
reviewed provisioning approach. Do not fall back to plaintext environment
variables or ad-hoc token files.

## 5. Verify the OpenClaw gateway boundary

The gateway must be healthy and loopback-only:

```bash
sudo ss -ltnp | grep 18789
openclaw gateway status --require-rpc
```

Acceptable listeners:

```text
127.0.0.1:18789
[::1]:18789
```

Any public, wildcard or non-loopback listener is a blocking failure.

The dedicated `cvn-broker` OpenClaw agent must remain text-only and restricted.
Do not grant browser, email, gateway-administration, unrestricted shell or
unrestricted filesystem tools as part of this runbook.

## 6. Install and validate the service

```bash
cd /opt/cvn-worker
sudo cp \
  deploy/cvn-openclaw-staging-worker.service \
  /etc/systemd/system/cvn-openclaw-staging-worker.service

sudo systemd-analyze verify \
  /etc/systemd/system/cvn-openclaw-staging-worker.service

sudo systemctl daemon-reload
```

Review the installed unit and confirm:

```text
CVN_BROKER_ENV=staging
CVN_TARGET_AGENT=openclaw
AGENT_BROKER_KEY_ID=vps-worker-staging
CVN_WORKER_ID=vps-worker-id-staging
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
```

The service must use `LoadCredentialEncrypted` for all three secret values.

## 7. Start without enabling at boot

```bash
sudo systemctl start cvn-openclaw-staging-worker.service
sudo systemctl status cvn-openclaw-staging-worker.service
sudo journalctl \
  -u cvn-openclaw-staging-worker.service \
  -n 100 \
  --no-pager
```

Expected:

- the banner identifies **Staging**;
- the gateway preflight passes;
- polling begins without authentication failures;
- no credential or payload value appears in logs; and
- the service does not restart unexpectedly.

Do not enable the service at boot yet.

## 8. Run the synthetic acceptance task

From the authorised Windows development machine:

```powershell
$env:CVN_BROKER_ENV = "staging"
uv run python scripts/submit_test_task_openclaw.py `
  --title "VPS Staging Test" `
  --target "openclaw" `
  --text "Return exactly: CVN_OPENCLAW_STAGING_OK"
```

Query the returned task ID using the signed status client:

```powershell
uv run python scripts/check_task_status.py CVN-TASK-ID
```

Acceptance requires:

1. one submission;
2. one claim by the staging OpenClaw worker;
3. one loopback gateway execution;
4. one completion;
5. final status `completed`;
6. result summary `CVN_OPENCLAW_STAGING_OK`; and
7. no raw transcript, audio path, credential or classroom data in remote logs.

## 9. Run failure-path checks

Use synthetic data only.

- Submit a `hermes` task and confirm this worker does not claim it.
- Stop the gateway, confirm a retryable gateway failure, restart it and confirm
  recovery.
- Verify duplicate completion does not replace the original success.
- Verify invalid authentication returns `401`.
- Verify cross-worker or wrong-target access returns `403`.

Do not weaken worker allowlists or broker authentication to make a check pass.

## 10. Enable only after acceptance

After the reviewed acceptance evidence passes:

```bash
sudo systemctl enable cvn-openclaw-staging-worker.service
sudo systemctl is-enabled cvn-openclaw-staging-worker.service
```

This enables the staging service only. It is not production promotion.

## Rollback and containment

On authentication, environment, restart, gateway or data-boundary failure:

```bash
sudo systemctl disable --now cvn-openclaw-staging-worker.service
sudo systemctl status cvn-openclaw-staging-worker.service
```

Then:

1. disable the affected staging worker identity at the broker;
2. preserve sanitised logs and the exact Git commit;
3. confirm previous credentials are rejected if rotation is required;
4. leave production identities unchanged;
5. do not delete broker or outbox evidence; and
6. require review before restarting.

## Related documentation

- [Phase 2E delivery plan](../docs/phase-2e-delivery-plan.md)
- [Environment and credential operations](../docs/operations/environment-and-credentials.md)
- [Outbox recovery](../docs/operations/outbox-recovery.md)
- [Worker contract](../docs/architecture/003-cvn-worker-contract.md)
