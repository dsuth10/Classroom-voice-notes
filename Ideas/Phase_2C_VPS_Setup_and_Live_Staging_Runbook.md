# Phase 2C VPS Setup and Live Staging Verification Runbook

**Project:** Classroom Voice Notes (CVN) Broker  
**Environment:** Supabase staging only  
**Staging project:** ukqkkgzimhtjhlnmlyao  
**Execution host:** Existing OpenClaw VPS  
**Date:** 10 July 2026  
**Audience:** Implementation agent with administrative access to the VPS

## 1. Objective

Install and verify the CVN OpenClaw worker on the existing VPS without exposing the OpenClaw gateway publicly.

Required execution path:

~~~text
Windows CVN
→ Supabase staging
→ CVN worker on VPS
→ OpenClaw on the same VPS through 127.0.0.1
→ Supabase staging
→ Windows CVN
~~~

Use synthetic test data only. Do not connect to production, deploy production migrations, use real classroom data or merge to main.

## 2. Safety rules

1. Work only against Supabase staging project ukqkkgzimhtjhlnmlyao.
2. Do not expose OpenClaw port 18789 publicly.
3. Do not start a second OpenClaw gateway.
4. Do not overwrite the existing OpenClaw configuration.
5. Back up configuration before modifying it.
6. Never print credentials, tokens, signatures or raw task payloads.
7. Do not rotate existing Supabase secrets without explicit approval.
8. Stop if the correct OpenClaw service owner or configuration cannot be identified.
9. Stop if the OpenClaw deep security audit reports unresolved critical findings.
10. Record all non-secret changes and rollback commands.

## 3. Stage 0 — Freeze and identify the code

Before touching the VPS:

1. Confirm all Phase 2C changes are committed.
2. Record the branch, commit hash, migration 006 checksum, test results and deployed staging Edge Function versions.
3. Confirm the exact commit is available to the VPS through the existing Git remote.
4. Do not deploy an uncommitted working tree or an arbitrary version of main.

### Acceptance gate

- The exact Phase 2C commit is known and available.
- The source working tree is clean.
- Milestone 2, broker-extension, adapter and worker tests are green.

## 4. Stage 1 — Inspect the VPS

Run read-only discovery first:

~~~bash
whoami
id
uname -a
cat /etc/os-release
openclaw --version
command -v openclaw
~~~

Locate the running gateway without restarting it:

~~~bash
ps -eo user,pid,cmd | grep -i '[o]penclaw'
ss -ltnp | grep 18789
~~~

Inspect possible services:

~~~bash
systemctl list-units --type=service | grep -i openclaw
systemctl --user list-units --type=service | grep -i openclaw
~~~

Determine and record:

- Linux distribution and OpenClaw version.
- User account running OpenClaw.
- Gateway service name and service manager.
- Active gateway configuration path.
- Gateway bind address, port and authentication mode.
- Existing agents and workspace locations.

The expected listener is 127.0.0.1:18789. If it is bound to 0.0.0.0, :: or a public address, stop and report this before continuing.

Run all later OpenClaw commands as the user who owns the existing OpenClaw installation.

## 5. Stage 2 — Back up OpenClaw configuration

Identify the active configuration path. It is commonly ~/.openclaw/openclaw.json, but do not assume this if a profile or OPENCLAW_CONFIG_PATH is used.

Create a timestamped backup without displaying its contents:

~~~bash
cp --preserve=all ACTIVE_CONFIG_PATH ACTIVE_CONFIG_PATH.pre-cvn-YYYYMMDD-HHMMSS
~~~

Record the resulting path. Validate the live system:

~~~bash
openclaw config schema
openclaw gateway status
openclaw status
~~~

Do not replace the whole configuration. Merge only the required settings.

## 6. Stage 3 — Create the restricted CVN agent

Using the OpenClaw owner account:

~~~bash
openclaw agents add cvn-broker \
  --workspace ~/.openclaw/workspace-cvn-broker \
  --non-interactive \
  --json
~~~

If this OpenClaw version requires a model, inspect the existing default and available models. Do not guess a model identifier.

Configure cvn-broker with:

- No skills.
- Sandbox mode all with agent-specific scope.
- No workspace access, if supported.
- No filesystem, shell, runtime or process tools.
- No browser, email, messaging or calendar tools.
- No cron or gateway administration tools.
- No sessions or sub-agent spawning.
- No elevated execution.

Conceptual configuration:

~~~json5
{
  id: "cvn-broker",
  workspace: "~/.openclaw/workspace-cvn-broker",
  skills: [],
  sandbox: {
    mode: "all",
    scope: "agent",
    workspaceAccess: "none"
  },
  tools: {
    allow: [],
    deny: [
      "group:fs",
      "group:runtime",
      "browser",
      "message",
      "cron",
      "gateway",
      "sessions_spawn"
    ]
  }
}
~~~

Validate all field names against the installed schema. Merge the agent into the existing agents list without replacing other agents. If an empty allowlist is unsupported, use the narrowest valid policy with no actionable tools.

### Acceptance gate

- cvn-broker exists exactly once.
- Existing agents are unchanged.
- The agent has no actionable tools, skills, sub-agent access or elevated execution.

## 7. Stage 4 — Enable the Responses endpoint

Enable:

~~~text
gateway.http.endpoints.responses.enabled = true
~~~

Prefer:

~~~bash
openclaw config set gateway.http.endpoints.responses.enabled true
~~~

Confirm the existing configuration remains:

~~~text
gateway.bind = loopback
gateway.port = 18789
gateway.auth.mode = token
~~~

Do not change the gateway token. Restart the established gateway through its existing service manager; do not start another foreground gateway.

Verify:

~~~bash
openclaw gateway status --require-rpc
openclaw status
ss -ltnp | grep 18789
openclaw security audit --deep
~~~

Stop if an unresolved critical security finding is reported.

## 8. Stage 5 — Verify the gateway locally

From the VPS, test:

~~~text
GET http://127.0.0.1:18789/v1/models
POST http://127.0.0.1:18789/v1/responses
~~~

Do not place the gateway token in shell history or command-line arguments. Load it through the existing secret mechanism or a protected temporary credential file.

Confirm the model list contains openclaw/cvn-broker. Send:

~~~json
{
  "model": "openclaw/cvn-broker",
  "input": "Return exactly: CVN adapter connection successful.",
  "user": "cvn-vps-smoke-test",
  "stream": false,
  "max_output_tokens": 200
}
~~~

Required result:

~~~text
CVN adapter connection successful.
~~~

Confirm no tool call was attempted or returned.

## 9. Stage 6 — Prepare the worker installation

Create a dedicated account if one does not already exist:

~~~bash
sudo useradd \
  --system \
  --home /var/lib/cvn-worker \
  --create-home \
  --shell /usr/sbin/nologin \
  cvn-worker
~~~

Install the exact verified commit under:

~~~text
/opt/classroom-voice-notes
~~~

The service account should be able to read the code but not modify it unnecessarily. Create the virtual environment and install dependencies from the repository's authoritative dependency file. Do not install unrecorded packages manually.

Verify imports:

~~~bash
/opt/classroom-voice-notes/.venv/bin/python -c \
  "from app.destinations.openclaw_adapter import OpenClawAdapter"
~~~

## 10. Stage 7 — Provision staging credentials

The VPS requires:

- Supabase worker bearer credential.
- Supabase worker HMAC secret.
- OpenClaw gateway credential.

Expected file-based interfaces:

~~~text
AGENT_BROKER_BEARER_TOKEN_FILE
AGENT_BROKER_HMAC_SECRET_FILE
OPENCLAW_GATEWAY_TOKEN_FILE
~~~

Use systemd LoadCredential where available. Do not copy or rotate credentials through logs or chat.

If secure staging credentials cannot be obtained, stop and report:

> VPS installation is ready, but staging worker credentials require secure provisioning.

Do not invent credentials or change Supabase Edge Function secrets without approval.

## 11. Stage 8 — Install the systemd service

Create /etc/systemd/system/cvn-openclaw-worker.service with an equivalent configuration:

~~~ini
[Unit]
Description=Classroom Voice Notes OpenClaw Broker Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cvn-worker
Group=cvn-worker
WorkingDirectory=/opt/classroom-voice-notes

ExecStart=/opt/classroom-voice-notes/.venv/bin/python scripts/watch_inbox_worker.py

Environment=CVN_ENV=staging
Environment=CVN_TARGET_AGENT=openclaw
Environment=OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
Environment=OPENCLAW_RESPONSES_PATH=/v1/responses
Environment=OPENCLAW_AGENT_ID=cvn-broker
Environment=AGENT_BROKER_BEARER_TOKEN_FILE=%d/cvn-broker-bearer
Environment=AGENT_BROKER_HMAC_SECRET_FILE=%d/cvn-broker-hmac
Environment=OPENCLAW_GATEWAY_TOKEN_FILE=%d/openclaw-gateway-token

LoadCredential=cvn-broker-bearer:/etc/cvn/credentials/broker-bearer
LoadCredential=cvn-broker-hmac:/etc/cvn/credentials/broker-hmac
LoadCredential=openclaw-gateway-token:/etc/cvn/credentials/openclaw-gateway-token

Restart=on-failure
RestartSec=10
TimeoutStopSec=30

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
~~~

Adjust variable names only if the implemented settings loader uses different names.

Verify the unit:

~~~bash
sudo systemd-analyze verify /etc/systemd/system/cvn-openclaw-worker.service
sudo systemctl daemon-reload
~~~

Start it without enabling boot startup:

~~~bash
sudo systemctl start cvn-openclaw-worker.service
sudo systemctl status cvn-openclaw-worker.service
sudo journalctl -u cvn-openclaw-worker.service --since "10 minutes ago"
~~~

Confirm the logs contain no secrets, signatures, nonces or raw payloads.

## 12. Stage 9 — Full staging test

From Windows, submit:

~~~json
{
  "target_agent": "openclaw",
  "task_type": "cvn.test",
  "payload": {
    "mode": "echo",
    "text": "Return exactly: CVN adapter connection successful."
  }
}
~~~

Verify:

1. The task enters cvn_tasks_queue_openclaw.
2. The VPS worker claims it.
3. The Hermes queue remains untouched.
4. The worker passes the same task_id to OpenClaw.
5. OpenClaw returns the expected text.
6. The adapter rejects tool calls.
7. Exactly one completion is recorded.
8. Status becomes completed.
9. retry_count remains 0.
10. No protected content appears in logs.

Record the task ID and sanitised status output.

## 13. Stage 10 — Live failure tests

Run each test separately.

### Gateway unavailable before dispatch

Stop the gateway through its normal service manager, submit a synthetic task, confirm the worker classifies it as unavailable, restart OpenClaw and confirm controlled recovery.

### Invalid gateway authentication

Use a temporary invalid credential in an isolated test configuration. Confirm the worker stops with a fatal configuration error. Restore the correct credential afterwards.

### Worker restart

Stop and restart the worker while idle. Confirm polling resumes and no duplicate worker remains.

### Target separation

Queue Hermes and OpenClaw tasks together. Confirm the OpenClaw worker claims only the OpenClaw task.

### Unknown execution state

Use a short controlled post-dispatch timeout. Confirm:

- Status becomes manual_review.
- The task leaves the active OpenClaw queue.
- The stale-claim reaper does not reclaim it.
- No duplicate execution occurs.

### Supabase outage

Temporarily block or misconfigure the staging endpoint without changing production settings. Confirm bounded backoff and recovery.

## 14. Stage 11 — Enable the worker

Only after all gates pass:

~~~bash
sudo systemctl enable cvn-openclaw-worker.service
sudo systemctl restart cvn-openclaw-worker.service
sudo systemctl is-enabled cvn-openclaw-worker.service
sudo systemctl is-active cvn-openclaw-worker.service
~~~

Do not install production credentials or production Supabase configuration.

## 15. Required completion report

Return:

- VPS operating system.
- OpenClaw version.
- OpenClaw service owner and gateway service name.
- Confirmed loopback listener.
- cvn-broker policy summary.
- Security-audit result.
- Worker installation path and systemd service name.
- Exact Git commit deployed.
- Staging task IDs and sanitised results.
- Confirmation of Hermes/OpenClaw queue separation.
- Confirmation that manual_review cannot be automatically reclaimed.
- Warnings, deviations and exact rollback steps.

Do not return credential values.

## 16. Rollback

If verification fails:

1. Stop and disable the worker.
2. Restore the timestamped OpenClaw configuration backup.
3. Restart the existing OpenClaw gateway service.
4. Confirm the earlier gateway state is healthy.
5. Preserve staging database evidence.
6. Do not delete failed or manual_review tasks before diagnosis.

Worker rollback:

~~~bash
sudo systemctl disable --now cvn-openclaw-worker.service
sudo journalctl -u cvn-openclaw-worker.service --since "1 hour ago"
~~~

Do not remove the installation or evidence until the failure is understood.

## 17. Stop conditions requiring user direction

Stop and report rather than improvising if:

- The gateway is publicly bound.
- More than one unexplained gateway is running.
- The active configuration cannot be identified.
- The installed schema differs materially from this runbook.
- The Phase 2C commit is unavailable.
- Secure staging credentials cannot be provisioned.
- A critical security finding remains.
- cvn-broker cannot be restricted to text-only operation.
- The worker would connect to anything other than staging.
- A live timeout can still cause automatic redispatch.
- A step requires production deployment or real classroom information.

## 18. Authoritative references

- [OpenClaw VPS guidance](https://docs.openclaw.ai/vps)
- [OpenClaw remote-access guidance](https://docs.openclaw.ai/gateway/remote)
- [OpenClaw OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api)
- [OpenClaw agent tool-policy guidance](https://docs.openclaw.ai/tools/multi-agent-sandbox-tools)
- [OpenClaw gateway security guidance](https://docs.openclaw.ai/gateway/security)
- [OpenClaw gateway exposure runbook](https://docs.openclaw.ai/gateway/security/exposure-runbook)

