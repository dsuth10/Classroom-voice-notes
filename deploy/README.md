# Phase 2C.2 VPS Provisioning and Live Staging Runbook

This document details the step-by-step procedure for provisioning, configuring, and verifying the CVN OpenClaw worker on the staging VPS.

---

## 📋 Prerequisites & Safety Rules

1. **Staging Isolation:** Only target the Supabase staging project `ukqkkgzimhtjhlnmlyao` and registered staging credentials.
2. **Gateway Protection:** Do NOT expose OpenClaw port `18789` publicly. It must remain loopback-only (`127.0.0.1`).
3. **No Secrets in History:** Never pass tokens or secrets in command-line arguments. Load them from files, environment files, or systemd credentials.
4. **Clean Code:** Deployed code must match the exact Git commit from `feature/phase-2c2-vps-staging-worker`.

---

## 🤖 OpenClaw Gateway Lifecycle & Supervisor

The staging VPS runs OpenClaw with the following supervisor structure:
*   **Supervisor:** Managed as a **systemd user service** for the `root` user (`openclaw-gateway.service`, defined at `/root/.config/systemd/user/openclaw-gateway.service`).
*   **Linger Configuration:** systemd lingering is **enabled** for the `root` user (via `/var/lib/systemd/linger/root`), which ensures root's user manager runs continuously on boot and user-level units stay active without an active SSH session.
*   **Failover / Restart Policy:** Configured with `Restart=always` and `RestartSec=5s`.
*   **Binding:** Bound exclusively to the loopback interface on port `18789` (`127.0.0.1:18789` and `[::1]:18789`).
*   **Dependencies:** The CVN staging worker runs as a system-level unit under an unprivileged `cvn-worker` account. Because system units cannot declare systemd dependencies on user units, the CVN worker has **no direct system-unit dependency** on the OpenClaw service. Instead, it relies on a robust `ExecStartPre` connection check (`deploy/wait_for_gateway.py`) that waits for loopback port 18789 to be ready before starting.

---

## 🛠️ Step 1: VPS Account and Layout Setup

Run the following commands on the VPS as root or using sudo:

```bash
# 1. Create the unprivileged cvn-worker service account
sudo useradd \
  --system \
  --home /var/lib/cvn-worker \
  --create-home \
  --shell /usr/sbin/nologin \
  cvn-worker

# 2. Setup the application directory
sudo mkdir -p /opt/cvn-worker
sudo chown -R $USER:cvn-worker /opt/cvn-worker
sudo chmod -R 750 /opt/cvn-worker

# 3. Setup the credential directory
sudo mkdir -p /etc/cvn/credentials
sudo chown -R root:cvn-worker /etc/cvn/credentials
sudo chmod 750 /etc/cvn/credentials
```

---

## 📦 Step 2: Deploy Codebase and Virtual Environment

Clone the repository and install dependencies inside `/opt/cvn-worker`:

```bash
cd /opt/cvn-worker

# Clone if not already present, or fetch the new branch
git fetch origin
git switch feature/phase-2c2-vps-staging-worker
git pull --ff-only

# Verify the deployed commit matches the local feature commit
git rev-parse HEAD

# Setup virtual environment
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

# Confirm imports work
.venv/bin/python -c "from app.destinations.openclaw_adapter import OpenClawAdapter"
```

---

## 🔑 Step 3: Secret Provisioning (Choose Method A or B)

Get the fresh staging-only credentials from your password vault:
- **Broker Bearer Token** (Supabase Edge Function header auth)
- **Broker HMAC Secret** (Payload signature verification)
- **OpenClaw Gateway Token** (Local OpenClaw HTTP API key)

### Method A: systemd Encrypted Credentials (Recommended)

*Requires systemd v250+.* Check systemd version using `systemd-analyze --version`.

Create the encrypted credentials directly for the service unit context:

```bash
# Set permissions temporarily to allow writing plaintext files
sudo chmod 700 /etc/cvn/credentials

# Write plaintext secrets to temporary files
sudo sh -c 'echo "YOUR_BEARER_TOKEN" > /etc/cvn/credentials/broker-bearer.tmp'
sudo sh -c 'echo "YOUR_HMAC_SECRET" > /etc/cvn/credentials/broker-hmac.tmp'
sudo sh -c 'echo "YOUR_GATEWAY_TOKEN" > /etc/cvn/credentials/openclaw-gateway-token.tmp'

# Restrict temporary files immediately
sudo chmod 600 /etc/cvn/credentials/*.tmp

# Encrypt for systemd context using credentials tool
sudo systemd-creds encrypt --name=cvn-broker-bearer /etc/cvn/credentials/broker-bearer.tmp /etc/cvn/credentials/broker-bearer
sudo systemd-creds encrypt --name=cvn-broker-hmac /etc/cvn/credentials/broker-hmac.tmp /etc/cvn/credentials/broker-hmac
sudo systemd-creds encrypt --name=openclaw-gateway-token /etc/cvn/credentials/openclaw-gateway-token.tmp /etc/cvn/credentials/openclaw-gateway-token

# Zero out and remove plaintext temporary files
sudo dd if=/dev/zero of=/etc/cvn/credentials/broker-bearer.tmp bs=1 count=100 conv=notrunc 2>/dev/null
sudo dd if=/dev/zero of=/etc/cvn/credentials/broker-hmac.tmp bs=1 count=100 conv=notrunc 2>/dev/null
sudo dd if=/dev/zero of=/etc/cvn/credentials/openclaw-gateway-token.tmp bs=1 count=100 conv=notrunc 2>/dev/null
sudo rm /etc/cvn/credentials/*.tmp

# Secure the credential directory permissions
sudo chmod 550 /etc/cvn/credentials
sudo chmod 440 /etc/cvn/credentials/*
sudo chown -R root:cvn-worker /etc/cvn/credentials
```

### Method B: locked-down systemd plaintext Environment File (Fallback)

If systemd encrypted credentials are unsupported, use standard file-based tokens:

```bash
# Write plaintext secrets directly to restricted files
sudo sh -c 'echo -n "YOUR_BEARER_TOKEN" > /etc/cvn/credentials/broker-bearer'
sudo sh -c 'echo -n "YOUR_HMAC_SECRET" > /etc/cvn/credentials/broker-hmac'
sudo sh -c 'echo -n "YOUR_GATEWAY_TOKEN" > /etc/cvn/credentials/openclaw-gateway-token'

# Secure files
sudo chmod 550 /etc/cvn/credentials
sudo chmod 440 /etc/cvn/credentials/*
sudo chown -R root:cvn-worker /etc/cvn/credentials
```

If using **Method B**, edit the service file `/etc/systemd/system/cvn-openclaw-worker.service` to map standard files:
Replace:
```ini
Environment=AGENT_BROKER_BEARER_TOKEN_FILE=%d/cvn-broker-bearer
Environment=AGENT_BROKER_HMAC_SECRET_FILE=%d/cvn-broker-hmac
Environment=OPENCLAW_GATEWAY_TOKEN_FILE=%d/openclaw-gateway-token

LoadCredentialEncrypted=cvn-broker-bearer:/etc/cvn/credentials/broker-bearer
LoadCredentialEncrypted=cvn-broker-hmac:/etc/cvn/credentials/broker-hmac
LoadCredentialEncrypted=openclaw-gateway-token:/etc/cvn/credentials/openclaw-gateway-token
```
With:
```ini
Environment=AGENT_BROKER_BEARER_TOKEN_FILE=/etc/cvn/credentials/broker-bearer
Environment=AGENT_BROKER_HMAC_SECRET_FILE=/etc/cvn/credentials/broker-hmac
Environment=OPENCLAW_GATEWAY_TOKEN_FILE=/etc/cvn/credentials/openclaw-gateway-token
```

---

## 🤖 Step 4: Configure OpenClaw restricted Agent

Verify the OpenClaw configuration and add the restricted agent `cvn-broker` under the OpenClaw owner account (typically the active user, e.g. `openclaw`):

```bash
# Add cvn-broker agent with restricted scope
openclaw agents add cvn-broker \
  --workspace ~/.openclaw/workspace-cvn-broker \
  --non-interactive \
  --json

# Configure responses endpoint to be active
openclaw config set gateway.http.endpoints.responses.enabled true

# Restart OpenClaw gateway to apply configuration changes
systemctl --user restart openclaw-gateway.service

# Confirm gateway is healthy and listening on 127.0.0.1:18789
sudo ss -ltnp | grep 18789
openclaw gateway status --require-rpc
```

---

## 🔍 Step 5: Environment Diagnostics

To ensure everything is correctly configured, run the non-destructive diagnostic script on the VPS:

```bash
# Export the environment variables for testing manually
export CVN_BROKER_ENV=staging
export CVN_WORKER_ID=vps-worker-id-staging
export AGENT_BROKER_KEY_ID=vps-worker-staging
export CVN_TARGET_AGENT=openclaw
export OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789

# Set the credential files (adapt path if using Method A systemd directory vs Method B)
# For Method B:
export AGENT_BROKER_BEARER_TOKEN_FILE=/etc/cvn/credentials/broker-bearer
export AGENT_BROKER_HMAC_SECRET_FILE=/etc/cvn/credentials/broker-hmac
export OPENCLAW_GATEWAY_TOKEN_FILE=/etc/cvn/credentials/openclaw-gateway-token

# Run diagnostics
/opt/cvn-worker/.venv/bin/python deploy/diagnose_worker.py
```

*Ensure the diagnostic script exits with `0` and shows `ALL CHECKS PASSED`.*

---

## 🚀 Step 6: Install and Start systemd Service

Copy the service file template into the system systemd directory:

```bash
sudo cp deploy/cvn-openclaw-staging-worker.service /etc/systemd/system/cvn-openclaw-worker.service

# Edit files paths if using Method B as described above
sudo nano /etc/systemd/system/cvn-openclaw-worker.service

# Validate and reload daemon
sudo systemd-analyze verify /etc/systemd/system/cvn-openclaw-worker.service
sudo systemctl daemon-reload

# Start service (Do NOT enable on boot yet!)
sudo systemctl start cvn-openclaw-worker.service
sudo systemctl status cvn-openclaw-worker.service
```

Inspect the logs to confirm healthy polling:
```bash
sudo journalctl -u cvn-openclaw-worker.service -n 50 --no-pager
```

---

## 🧪 Step 7: Controlled Live Verification Task

From your local Windows machine:

```powershell
# Submit test task targeting the openclaw agent
.venv\Scripts\python scripts\submit_test_task_openclaw.py --title "VPS Staging Test" --target "openclaw" --text "Return exactly: CVN_OPENCLAW_STAGING_OK"
```

Verify that the VPS logs show the claim, execution on loopback gateway, and successful completion.
Query the task status from the local machine:
```powershell
.venv\Scripts\python scripts\check_task_status.py <TASK_ID>
```
Confirm:
- Status is `completed`
- Result contains `CVN_OPENCLAW_STAGING_OK`
- No secrets are leaked.

---

## 🔄 Step 8: Post-Verification Failure-Path Tests

Run the following negative and recovery tests on the VPS:

1. **Target Separation Check:**
   Submit a task targeting `hermes`. Confirm the VPS worker does NOT claim it.
2. **Gateway Interruption:**
   Stop the gateway (`systemctl --user stop openclaw-gateway.service`). Submit a task. Confirm the worker reports a `retryable` gateway failure and backs off safely. Restart the gateway and confirm automatic recovery.
3. **Duplicate Completion:**
   Ensure completing the same task twice is rejected on the broker backend (check that first success remains).

---

## 🏁 Step 9: Final Activation

If all gates pass, enable the worker on boot:

```bash
sudo systemctl enable cvn-openclaw-worker.service
```
