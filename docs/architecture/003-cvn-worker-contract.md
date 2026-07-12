# Worker Contract - CVN Broker Interface

This document defines the formal boundary and API contract between the Classroom Voice Notes (CVN) Broker and external processing agents (workers) such as OpenClaw. It guarantees structural consistency, safety, and reliability across continuous task lifecycles.

---

## 1. Request & Response Envelope Schemas

All communication with the broker is conducted over HTTPS using Edge Functions. Task bodies and response payloads conform to the versioned envelopes below.

### 1.1. Authentication Headers

All requests made by workers (Claim, Complete, Fail) must include the following headers:
- `Authorization`: `Bearer <credential>`
- `x-cvn-signature`: HMAC SHA-256 signature over the request body (or canonical URL string for GET requests).
- `x-cvn-key-id`: The unique worker key identifier issued during credential provisioning.

If `x-cvn-key-id` is omitted, the broker falls back to legacy shared-credential authentication (deprecated; scheduled for complete removal in Milestone 3.0).

### 1.2. CVN Task Submission (Client Envelope)
* **Endpoint:** `POST /functions/v1/cvn-submit-task`
* **Schema Version:** `cvn.agent_task.v1`
* **JSON Structure:**
```json
{
  "schema_version": "cvn.agent_task.v1",
  "task_id": "CVN-YYYYMMDD-HHMMSS-XXXX",
  "created_at": "ISO-8601-UTC-TIMESTAMP",
  "source": "classroom_voice_notes",
  "source_device_id": "device_identifier",
  "target_agent": "hermes | openclaw | auto",
  "privacy": {
    "classification": "non_sensitive",
    "policy_gate_version": "1.0.0",
    "checks_passed": ["category_agent_task"]
  },
  "task": {
    "title": "Short descriptive title",
    "instructions": "Task-specific instructions (JSON string or raw text)",
    "priority": "low | normal | high | urgent"
  },
  "redactions_applied": [],
  "signed_at": "ISO-8601-UTC-TIMESTAMP",
  "nonce": "cryptographic_nonce_hex_16_to_64_chars",
  "idempotency_key": "unique_idempotency_key_uuid"
}
```

### 1.2. Claim Task (Worker Request/Response)
* **Endpoint:** `POST /functions/v1/cvn-claim-task`
* **Request Structure:**
```json
{
  "worker_id": "worker_identifier",
  "vt_seconds": 1800,
  "target_agent": "hermes | openclaw",
  "signed_at": "ISO-8601-UTC-TIMESTAMP",
  "nonce": "nonce_hex_16"
}
```
* **Response Structure (Claimed):**
```json
{
  "claimed": true,
  "task_id": "CVN-YYYYMMDD-HHMMSS-XXXX",
  "target_agent": "hermes | openclaw | auto",
  "status": "claimed",
  "payload": {
    "schema_version": "cvn.agent_task.v1",
    "task_id": "CVN-YYYYMMDD-HHMMSS-XXXX",
    "task": {
      "title": "...",
      "instructions": "..."
    }
  }
}
```

### 1.3. Complete Task (Worker Request/Response)
* **Endpoint:** `POST /functions/v1/cvn-complete-task`
* **Request Structure:**
```json
{
  "task_id": "CVN-YYYYMMDD-HHMMSS-XXXX",
  "worker_id": "worker_identifier",
  "result_summary": "Summary of output/actions",
  "signed_at": "ISO-8601-UTC-TIMESTAMP",
  "nonce": "nonce_hex_16"
}
```
* **Response Structure:**
```json
{
  "success": true,
  "message": "completed | already_completed"
}
```

### 1.4. Fail Task (Worker Request/Response)
* **Endpoint:** `POST /functions/v1/cvn-fail-task`
* **Request Structure:**
```json
{
  "task_id": "CVN-YYYYMMDD-HHMMSS-XXXX",
  "worker_id": "worker_identifier",
  "failure": {
    "code": "UNSUPPORTED_TASK_TYPE | INVALID_TASK_PAYLOAD | CONNECT_TIMEOUT | etc",
    "message": "Sanitised error details",
    "disposition": "retryable | permanent | execution_unknown"
  },
  "signed_at": "ISO-8601-UTC-TIMESTAMP",
  "nonce": "nonce_hex_16"
}
```
* **Response Structure:**
```json
{
  "success": true,
  "status": "pending | dead_letter | manual_review",
  "retry_count": 1
}
```

---

## 2. Allowed Task Types & Schemas

Workers evaluate task instructions based on domain-oriented task types. When instructions are formatted as JSON, they must define `task_type` and supply matching `payload` parameters.

### 2.1. Domain Task Types
1. **`classroom_note.action`**: Extraction of action items or checklist items from a transcript.
2. **`classroom_note.summary`**: Synthesising and formatting structured classroom voice summaries.
3. **`classroom_note.resource_request`**: Formulating external digital resources/PDF requests.
4. **`cvn.test`**: Verification test task for E2E validation.

### 2.2. Test Task Schema (`cvn.test`)
* **Payload Fields:**
  - `test_mode`: `success | fail_once | fail_always | delay | crash_after_claim`

---

## 3. Operational Mechanics

### 3.1. Visibility Deadline & Claim Ownership
- **Timeout Duration:** The default visibility timeout (`p_vt_seconds`) is **1800 seconds (30 minutes)**.
- **Claim Token Ownership:** Upon a successful claim, the worker receives exclusive ownership of the task. If processing does not finish within 30 minutes, the task claim is considered stale. The internal database cleanup script (`cvn_reap_stale_claims`) will automatically release the claim, increment the retry counter, and make it available for reclamation.
- **Idempotency:** Completion and failure requests are idempotent. If a worker completes an already completed task, the broker returns `success: true` with status `already_completed` rather than failing.

### 3.2. Retry Limits & Failure Handling
- **Maximum Retry Limit:** Tasks are permitted a maximum of **5 attempts** (initial run + 4 retries) under the `retryable` disposition.
- **Failure Dispositions:**
  - **`retryable`**: Submitted via `cvn-fail-task` with transient error messages. The task transitions to `pending` and is requeued. It transitions to `dead_letter` when the 5-attempt limit is reached.
  - **`permanent`**: Submitted via `cvn-fail-task` for terminal validation or contract errors. The task transitions immediately to `dead_letter` and is removed from the active queue to avoid unnecessary retries.
  - **`execution_unknown`**: Submitted via `cvn-fail-task` when a read timeout occurs after successful request dispatch. The task transitions immediately to `manual_review` and is removed from the active queue to prevent automated duplicate execution.
- **Unsupported Version Handling:** If a worker encounters an unsupported envelope `schema_version`, it must fail the task with `disposition: permanent` and the message `"Unsupported schema version: [version]"` to prevent execution loops.

---

## 4. Privacy, Logging & Constraints

### 4.1. Payload Limits
- **Maximum Instruction Length:** 5,000 characters.
- **Maximum Title Length:** 200 characters.
- **Maximum Error Message Length:** 1,000 characters.

### 4.2. Logging and Privacy Restrictions
- **No Secret Logging:** Workers must never log or output HTTP Authorization headers, HMAC signatures, nonces, or raw credential tokens to console logs or file registries.
- **Redaction Integrity:** Workers must respect the `privacy` classification and ensure no raw transcript secrets or student identification records are exposed outside the secure enclave boundaries.
