# tests/integration/test_supabase_broker_milestone_2.py
# Run against staging ONLY. Load secrets from environment variables — never hardcode.
#
# Required env vars:
#   CVN_BEARER_TOKEN           — client (CVN app) bearer token
#   CVN_HMAC_SECRET            — client HMAC secret
#   AGENT_BROKER_BEARER_TOKEN  — worker bearer token
#   AGENT_BROKER_HMAC_SECRET   — worker HMAC secret
import os
import sys
import subprocess
import secrets
import datetime
import hashlib
import hmac
import requests
import json

# Target staging project ref only — never production
PROJECT_REF = "ukqkkgzimhtjhlnmlyao"
BASE_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1"

def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"[-] Missing required environment variable: {name}")
        sys.exit(1)
    return val

# Fail fast if secrets are missing
CLIENT_BEARER = _require_env("CVN_BEARER_TOKEN")
CLIENT_HMAC   = _require_env("CVN_HMAC_SECRET")
WORKER_BEARER = _require_env("AGENT_BROKER_BEARER_TOKEN")
WORKER_HMAC   = _require_env("AGENT_BROKER_HMAC_SECRET")


def run_db_query(sql: str) -> dict:
    """Executes a SQL query on staging via Supabase CLI."""
    res = subprocess.run(
        ["npx", "--prefer-offline", "supabase", "db", "query", "--linked", sql],
        capture_output=True,
        text=True,
        shell=True
    )
    if res.returncode != 0:
        raise RuntimeError(f"SQL execution failed: {res.stderr}\nStdout: {res.stdout}")

    # CLI emits preamble lines (e.g. "Initialising login role...") before the JSON block.
    # Strip everything before the first '{' to get clean JSON.
    stdout = res.stdout.strip()
    json_start = stdout.find("{")
    if json_start == -1:
        # No JSON returned (e.g. DDL with no result set) — return empty rows
        return {"rows": []}
    try:
        return json.loads(stdout[json_start:])
    except Exception as e:
        raise RuntimeError(f"Failed to parse SQL output: {e}\nRaw: {res.stdout}")

def hmac_sha256_hex(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()

def clean_database():
    print("[*] Cleaning up staging database before test...")
    # Run each statement separately — TRUNCATE CASCADE may be slow under a combined statement
    run_db_query("truncate table public.cvn_task_events cascade")
    run_db_query("delete from public.cvn_tasks")
    run_db_query("delete from public.cvn_processed_nonces")
    run_db_query("select pgmq.purge_queue('cvn_tasks_queue')")
    print("[+] Database clean.")

def test_milestone_2():
    client_bearer = CLIENT_BEARER
    client_hmac   = CLIENT_HMAC
    worker_bearer = WORKER_BEARER
    worker_hmac   = WORKER_HMAC

    clean_database()
    
    print("\n[*] Scenario 1: Claim when queue is empty")
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "worker_id": "test-worker-01",
        "vt_seconds": 1800,
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    body_str = json.dumps(payload, separators=(",", ":"))
    sig = hmac_sha256_hex(body_str, worker_hmac)
    
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=body_str,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200, f"Status: {res.status_code} {res.text}"
    data = res.json()
    assert data["claimed"] is False
    assert data["reason"] == "no_pending_tasks"
    print("[+] Scenario 1: Passed")

    # =====================================================================
    # 2. Authentication Negative Tests
    # =====================================================================
    print("\n[*] Scenario 2: Bad authentication checks")
    # 2.1. Bad bearer token
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=body_str,
        headers={
            "Authorization": "Bearer badbearer",
            "x-cvn-signature": sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 401
    
    # 2.2. Tampered signature
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=body_str,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": "badsig",
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 401
    print("[+] Scenario 2: Passed")

    # =====================================================================
    # 3. Submit task, claim task
    # =====================================================================
    print("\n[*] Scenario 3: Submit and claim task")
    task_id = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()
    submit_payload = {
        "schema_version": "cvn.agent_task.v1",
        "task_id": task_id,
        "created_at": now.isoformat(),
        "source": "classroom_voice_notes",
        "source_device_id": "test-device-01",
        "target_agent": "hermes",
        "privacy": {
            "classification": "non_sensitive",
            "policy_gate_version": "1.0.0",
            "checks_passed": ["category_agent_task"]
        },
        "task": {
            "title": "Staging E2E Test Task",
            "instructions": "Verify the Milestone 2 queue flows."
        },
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
        "idempotency_key": "key-" + secrets.token_hex(8)
    }
    
    sub_body = json.dumps(submit_payload, separators=(",", ":"))
    sub_sig = hmac_sha256_hex(sub_body, client_hmac)
    
    res = requests.post(
        f"{BASE_URL}/cvn-submit-task",
        data=sub_body,
        headers={
            "Authorization": f"Bearer {client_bearer}",
            "x-cvn-signature": sub_sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200, f"Submit failed: {res.text}"
    print(f"[+] Task submitted successfully: {task_id}")

    # Claim the task
    claim_payload = {
        "worker_id": "test-worker-01",
        "vt_seconds": 1800,
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    claim_body = json.dumps(claim_payload, separators=(",", ":"))
    claim_sig = hmac_sha256_hex(claim_body, worker_hmac)
    
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=claim_body,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": claim_sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200, f"Claim failed: {res.text}"
    claim_data = res.json()
    assert claim_data["claimed"] is True
    assert claim_data["task_id"] == task_id
    assert claim_data["target_agent"] == "hermes"
    assert claim_data["status"] == "claimed"
    print("[+] Task claimed successfully.")
    
    # Verify db contains queue_msg_id
    db_rows = run_db_query(f"select queue_msg_id, status, claimed_by from public.cvn_tasks where task_id = '{task_id}'")
    row = db_rows["rows"][0]
    assert row["status"] == "claimed"
    assert row["claimed_by"] == "test-worker-01"
    assert row["queue_msg_id"] is not None
    queue_msg_id = row["queue_msg_id"]
    print(f"[+] Persisted queue_msg_id verified in DB: {queue_msg_id}")
    print("[+] Scenario 3: Passed")

    # =====================================================================
    # 4. Concurrent claims
    # =====================================================================
    print("\n[*] Scenario 4: Concurrent claim attempt on claimed task")
    concurrent_payload = {
        "worker_id": "test-worker-02",
        "vt_seconds": 1800,
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    concurrent_body = json.dumps(concurrent_payload, separators=(",", ":"))
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=concurrent_body,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": hmac_sha256_hex(concurrent_body, worker_hmac),
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200
    con_data = res.json()
    assert con_data["claimed"] is False
    print("[+] Concurrent claim rejected properly.")
    print("[+] Scenario 4: Passed")

    # =====================================================================
    # 5. Complete task & Idempotency
    # =====================================================================
    print("\n[*] Scenario 5: Complete task and verify idempotency")
    complete_payload = {
        "task_id": task_id,
        "worker_id": "test-worker-01",
        "result_summary": "Task processed successfully in staging.",
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    comp_body = json.dumps(complete_payload, separators=(",", ":"))
    comp_sig = hmac_sha256_hex(comp_body, worker_hmac)
    
    res = requests.post(
        f"{BASE_URL}/cvn-complete-task",
        data=comp_body,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": comp_sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200, f"Complete failed: {res.text}"
    comp_data = res.json()
    assert comp_data["success"] is True
    assert comp_data["message"] == "completed"
    
    # Verify db state
    db_rows = run_db_query(f"select status, queue_msg_id, result_summary from public.cvn_tasks where task_id = '{task_id}'")
    row = db_rows["rows"][0]
    assert row["status"] == "completed"
    assert row["queue_msg_id"] is None
    assert row["result_summary"] == "Task processed successfully in staging."
    print("[+] Task marked completed in DB and queue_msg_id set to NULL.")

    # Test idempotency (complete again)
    idem_payload = {
        "task_id": task_id,
        "worker_id": "test-worker-01",
        "result_summary": "Task processed successfully in staging.",
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    idem_body = json.dumps(idem_payload, separators=(",", ":"))
    res = requests.post(
        f"{BASE_URL}/cvn-complete-task",
        data=idem_body,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": hmac_sha256_hex(idem_body, worker_hmac),
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200
    comp_data = res.json()
    assert comp_data["success"] is True
    assert comp_data["message"] == "already_completed"
    print("[+] Idempotent complete call handled successfully.")
    print("[+] Scenario 5: Passed")

    # =====================================================================
    # 6. Fail task (requeuing and dead-letter)
    # =====================================================================
    print("\n[*] Scenario 6: Fail task retry limits")
    # Submit fresh task
    task_id2 = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()
    submit_payload["task_id"] = task_id2
    submit_payload["idempotency_key"] = "key-" + secrets.token_hex(8)
    submit_payload["nonce"] = secrets.token_hex(16)
    
    sub_body = json.dumps(submit_payload, separators=(",", ":"))
    sub_sig = hmac_sha256_hex(sub_body, client_hmac)
    requests.post(
        f"{BASE_URL}/cvn-submit-task",
        data=sub_body,
        headers={
            "Authorization": f"Bearer {client_bearer}",
            "x-cvn-signature": sub_sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    
    # Claim it
    claim_payload["nonce"] = secrets.token_hex(16)
    claim_body = json.dumps(claim_payload, separators=(",", ":"))
    claim_sig = hmac_sha256_hex(claim_body, worker_hmac)
    requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=claim_body,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": claim_sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )

    # Fail it 1 time (requeues to pending)
    fail_payload = {
        "task_id": task_id2,
        "worker_id": "test-worker-01",
        "error_message": "Temporary execution failure.",
        "signed_at": now.isoformat(),
        "nonce": secrets.token_hex(16)
    }
    fail_body = json.dumps(fail_payload, separators=(",", ":"))
    fail_sig = hmac_sha256_hex(fail_body, worker_hmac)
    
    res = requests.post(
        f"{BASE_URL}/cvn-fail-task",
        data=fail_body,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": fail_sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200, f"Fail failed: {res.text}"
    fail_data = res.json()
    assert fail_data["success"] is True
    assert fail_data["status"] == "pending"
    assert fail_data["retry_count"] == 1
    
    # Verify db status is pending (requeued)
    db_rows = run_db_query(f"select status, retry_count from public.cvn_tasks where task_id = '{task_id2}'")
    assert db_rows["rows"][0]["status"] == "pending"
    print("[+] Task successfully returned to pending after single failure.")

    # Fail 4 more times (total 5 times) to trigger dead-letter
    for i in range(2, 6):
        # Claim again
        claim_payload["nonce"] = secrets.token_hex(16)
        claim_body = json.dumps(claim_payload, separators=(",", ":"))
        claim_sig = hmac_sha256_hex(claim_body, worker_hmac)
        requests.post(
            f"{BASE_URL}/cvn-claim-task",
            data=claim_body,
            headers={
                "Authorization": f"Bearer {worker_bearer}",
                "x-cvn-signature": claim_sig,
                "Content-Type": "application/json"
            },
            timeout=60.0
        )

        # Fail again
        fail_payload["nonce"] = secrets.token_hex(16)
        fail_body = json.dumps(fail_payload, separators=(",", ":"))
        fail_sig = hmac_sha256_hex(fail_body, worker_hmac)
        res = requests.post(
            f"{BASE_URL}/cvn-fail-task",
            data=fail_body,
            headers={
                "Authorization": f"Bearer {worker_bearer}",
                "x-cvn-signature": fail_sig,
                "Content-Type": "application/json"
            },
            timeout=60.0
        )
        assert res.status_code == 200
        
    # Verify database is now dead_letter
    db_rows = run_db_query(f"select status, retry_count from public.cvn_tasks where task_id = '{task_id2}'")
    assert db_rows["rows"][0]["status"] == "dead_letter"
    assert db_rows["rows"][0]["retry_count"] == 5
    print("[+] Task successfully moved to dead_letter after 5 failures.")
    print("[+] Scenario 6: Passed")

    # =====================================================================
    # 7. Stale claim reaping
    # =====================================================================
    print("\n[*] Scenario 7: Reap stale claims")
    task_id3 = "CVN-" + now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2).upper()
    submit_payload["task_id"] = task_id3
    submit_payload["idempotency_key"] = "key-" + secrets.token_hex(8)
    submit_payload["nonce"] = secrets.token_hex(16)
    
    requests.post(
        f"{BASE_URL}/cvn-submit-task",
        data=json.dumps(submit_payload, separators=(",", ":")),
        headers={
            "Authorization": f"Bearer {client_bearer}",
            "x-cvn-signature": hmac_sha256_hex(json.dumps(submit_payload, separators=(",", ":")), client_hmac),
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    
    # Claim task
    claim_payload["nonce"] = secrets.token_hex(16)
    requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=json.dumps(claim_payload, separators=(",", ":")),
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": hmac_sha256_hex(json.dumps(claim_payload, separators=(",", ":")), worker_hmac),
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    
    # Expire expires_at manually in database
    run_db_query(f"update public.cvn_tasks set expires_at = now() - interval '1 second' where task_id = '{task_id3}'")
    print("[+] Expired expires_at in DB.")
    
    # Claim next task (triggers stale claim reaping internally!)
    claim_payload["nonce"] = secrets.token_hex(16)
    requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=json.dumps(claim_payload, separators=(",", ":")),
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": hmac_sha256_hex(json.dumps(claim_payload, separators=(",", ":")), worker_hmac),
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    
    # Verify task is returned to pending and retry_count is 1
    db_rows = run_db_query(f"select status, retry_count from public.cvn_tasks where task_id = '{task_id3}'")
    assert db_rows["rows"][0]["status"] == "pending"
    assert db_rows["rows"][0]["retry_count"] == 1
    print("[+] Stale claim successfully reaped and requeued.")
    print("[+] Scenario 7: Passed")

    # =====================================================================
    # 8. Nonce replay protection
    # =====================================================================
    print("\n[*] Scenario 8: Nonce replay protection")
    nonce_val = secrets.token_hex(16)
    claim_payload["nonce"] = nonce_val
    body_str = json.dumps(claim_payload, separators=(",", ":"))
    sig = hmac_sha256_hex(body_str, worker_hmac)
    
    # First call: OK
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=body_str,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 200
    
    # Second call: Duplicate nonce -> 401
    res = requests.post(
        f"{BASE_URL}/cvn-claim-task",
        data=body_str,
        headers={
            "Authorization": f"Bearer {worker_bearer}",
            "x-cvn-signature": sig,
            "Content-Type": "application/json"
        },
        timeout=60.0
    )
    assert res.status_code == 401
    assert res.json()["error"] == "duplicate_nonce"
    print("[+] Replay attack with duplicate nonce successfully blocked.")
    print("[+] Scenario 8: Passed")

    # =====================================================================
    # 9. Status endpoint (GET with signing)
    # =====================================================================
    print("\n[*] Scenario 9: Query status safely")
    nonce_status = secrets.token_hex(16)
    canonical = f"GET\n/functions/v1/cvn-status/{task_id}\ntask_id={task_id}\nsigned_at={now.isoformat()}\nnonce={nonce_status}"
    status_sig = hmac_sha256_hex(canonical, client_hmac)
    
    res = requests.get(
        f"{BASE_URL}/cvn-status/{task_id}?signed_at={now.isoformat()}&nonce={nonce_status}",
        headers={
            "Authorization": f"Bearer {client_bearer}",
            "x-cvn-signature": status_sig
        },
        timeout=60.0
    )
    assert res.status_code == 200, f"Status failed: {res.text}"
    status_data = res.json()
    assert status_data["task_id"] == task_id
    assert status_data["status"] == "completed"
    assert "result_summary" in status_data
    assert "payload_json" not in status_data
    assert "payload" not in status_data
    print("[+] Verified task status payload is restricted to safe columns only.")
    print("[+] Scenario 9: Passed")

    print("\n[+] ALL STAGING TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    test_milestone_2()
