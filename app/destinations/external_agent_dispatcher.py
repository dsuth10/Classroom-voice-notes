import httpx
import json
import os
import platform
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from app.config import keyring_store
from app.config.settings import SettingsManager
from app.destinations.external_outbox import ExternalOutbox
from app.destinations.payload_builder import build_payload
from app.destinations.hmac_signer import sign
from app.ollama_router.policy_gate import PolicyGate
from app.audit.audit_logger import log_audit_event

class ExternalAgentDispatcher:
    def __init__(self, settings_manager: SettingsManager, outbox: Optional[ExternalOutbox] = None) -> None:
        self.settings_manager = settings_manager
        self.outbox = outbox or ExternalOutbox()

    def get_source_device_id(self) -> str:
        """Retrieves source_device_id from settings, generating and saving a default one if empty."""
        device_id = self.settings_manager.get("external_agent.source_device_id")
        if not device_id:
            # Auto-generate a stable device ID based on hostname
            hostname = platform.node() or "unknown-pc"
            # Sanitise hostname to alphanumeric/hyphens
            hostname_clean = re.sub(r"[^A-Za-z0-9\-]", "", hostname).lower()
            random_suffix = f"{datetime.now().microsecond % 10000:04d}"
            device_id = f"cvn-{hostname_clean}-{random_suffix}"
            self.settings_manager.set("external_agent.source_device_id", device_id)
            log_audit_event("DEVICE_ID_GENERATED", "system", f"Generated source_device_id: {device_id}")
        return str(device_id)

    def resolve_agent(self, transcript: str, classification_data: Dict[str, Any]) -> str:
        """Determines target agent (hermes or openclaw) based on transcript keywords or classification."""
        transcript_lower = transcript.lower()
        if "openclaw" in transcript_lower or "open claw" in transcript_lower:
            return "openclaw"
        if "hermes" in transcript_lower:
            return "hermes"
        
        agent_target = classification_data.get("agent_target")
        if agent_target in ("hermes", "openclaw"):
            return agent_target
            
        default_agent = self.settings_manager.get("external_agent.target_agent_default") or "openclaw"
        return str(default_agent)

    def dispatch(self, classification_data: Dict[str, Any], note_path: str, transcript: str = "") -> bool:
        """Validates external routing policy, signs the payload, enqueues, and transmits it."""
        # 1. Check if disabled globally
        enabled = self.settings_manager.external_sharing_enabled()
        if not enabled:
            log_audit_event("EXTERNAL_DISPATCH_DISABLED", "dispatcher", "External agent dispatch is disabled in settings.")
            return False

        # 2. Check credentials exist using central environment resolver
        try:
            from app.config.environment import get_env_credential_ref
            hmac_ref = get_env_credential_ref("hmac_secret")
            bearer_ref = get_env_credential_ref("bearer_token")
        except Exception as e:
            log_audit_event("EXTERNAL_DISPATCH_FAILED", "dispatcher", f"Environment configuration error: {e}")
            self._update_note_frontmatter(Path(note_path), {"status": "dispatch_failed"})
            return False
        
        hmac_secret = keyring_store.get_secret(hmac_ref)
        bearer_token = keyring_store.get_secret(bearer_ref)
        
        if not hmac_secret or not bearer_token:
            log_audit_event(
                "EXTERNAL_DISPATCH_FAILED", 
                "dispatcher", 
                "Credentials missing from keyring. Dispatch blocked."
            )
            self._update_note_frontmatter(Path(note_path), {"status": "dispatch_failed"})
            return False

        # 3. Resolve target agent and config details
        target_agent = self.resolve_agent(transcript, classification_data)
        source_device_id = self.get_source_device_id()
        endpoint_url = self.settings_manager.get("external_agent.endpoint_url")

        try:
            from app.config.environment import validate_broker_endpoint
            validate_broker_endpoint(endpoint_url)
        except RuntimeError as exc:
            log_audit_event(
                "EXTERNAL_DISPATCH_BLOCKED",
                "dispatcher",
                f"Broker endpoint validation failed: {exc}",
            )
            self._update_note_frontmatter(Path(note_path), {"status": "dispatch_failed"})
            return False
        
        # 4. Build draft payload for policy gate checking
        draft_payload, _, _ = build_payload(
            classification_data=classification_data,
            source_device_id=source_device_id,
            target_agent=target_agent,
            checks_passed=[]
        )

        # 5. Run hardened policy checks
        gate = PolicyGate()
        vault_path = self.settings_manager.get("obsidian_vault_path")
        external_agent_config = self.settings_manager.get("external_agent") or {}
        
        allowed, checks_passed = gate.is_external_dispatch_allowed(
            category=classification_data.get("category", ""),
            sensitivity=classification_data.get("sensitivity", ""),
            safe_task=classification_data.get("task") or classification_data,
            transcript=transcript,
            payload=draft_payload,
            source_device_id=source_device_id,
            target_agent=target_agent,
            endpoint_url=endpoint_url,
            vault_path=vault_path,
            config=external_agent_config
        )

        if not allowed:
            log_audit_event(
                "EXTERNAL_DISPATCH_BLOCKED",
                "dispatcher",
                "Policy check failed. Dispatch blocked for task."
            )
            self._update_note_frontmatter(Path(note_path), {"status": "policy_blocked"})
            return False

        # 6. Rebuild payload with verified checks_passed list
        payload, json_str, payload_hash = build_payload(
            classification_data=classification_data,
            source_device_id=source_device_id,
            target_agent=target_agent,
            checks_passed=checks_passed
        )

        # 7. Enqueue locally in pending state
        local_id = self.outbox.enqueue(
            task_id=payload["task_id"],
            endpoint_url=endpoint_url,
            payload_json=json_str,
            payload_hash=payload_hash,
            idempotency_key=payload["idempotency_key"],
            nonce=payload["nonce"],
            schema_version="cvn.agent_task.v1",
            note_path=note_path,
            target_agent=target_agent,
        )

        # 8. Generate 5-element HMAC request headers
        from app.destinations.hmac_signer import create_client_request_headers
        client_key_id = self.settings_manager.get("external_agent.client_key_id") or os.environ.get("CVN_CLIENT_KEY_ID", "default_client_key")
        headers = create_client_request_headers(
            method="POST",
            endpoint_url=endpoint_url,
            raw_body_str=json_str,
            bearer_token=bearer_token,
            hmac_secret=hmac_secret,
            client_key_id=client_key_id,
            nonce=payload.get("nonce"),
        )

        self.outbox.mark_sending(local_id)
        
        try:
            response = httpx.post(endpoint_url, content=json_str, headers=headers, timeout=15.0)
            if response.status_code == 200:
                resp_json = response.json()
                remote_msg_id = resp_json.get("msg_id") or resp_json.get("task_id")
                self.outbox.mark_sent(local_id, remote_msg_id)
                self._update_note_frontmatter(Path(note_path), {
                    "status": "sent",
                    "task_id": payload["task_id"],
                    "agent_target": target_agent,
                    "submitted_at": datetime.now().astimezone().isoformat()
                })
                self._update_note_result_block(
                    file_path=Path(note_path),
                    status="sent",
                    agent=target_agent,
                    task_id=payload["task_id"],
                    timestamp_str=datetime.now().astimezone().isoformat(),
                    result_summary="Task submitted to broker."
                )
                return True
            elif response.status_code == 409:
                self.outbox.mark_duplicate(local_id, response.text)
                self._update_note_frontmatter(Path(note_path), {
                    "status": "sent",
                    "task_id": payload["task_id"],
                    "agent_target": target_agent,
                    "submitted_at": datetime.now().astimezone().isoformat()
                })
                self._update_note_result_block(
                    file_path=Path(note_path),
                    status="sent",
                    agent=target_agent,
                    task_id=payload["task_id"],
                    timestamp_str=datetime.now().astimezone().isoformat(),
                    result_summary="Task submitted to broker (duplicate collision resolved)."
                )
                return True
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                self.outbox.mark_failed(local_id, error_msg)
                self._update_note_frontmatter(Path(note_path), {"status": "dispatch_failed"})
                return False
        except Exception as e:
            error_msg = str(e)
            self.outbox.mark_failed(local_id, error_msg)
            self._update_note_frontmatter(Path(note_path), {"status": "dispatch_failed"})
            return False

    def retry_pending(
        self,
        manual: bool = False,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Retries all pending tasks in the outbox that are past their next_retry_at time."""
        self.outbox.expire_old(days=7)
        pending_tasks = self.outbox.get_pending()
        if not pending_tasks:
            return 0

        from app.config.environment import validate_broker_endpoint
        approved_tasks = []
        for task in pending_tasks:
            if should_stop and should_stop():
                return 0
            try:
                validate_broker_endpoint(task["endpoint_url"])
                approved_tasks.append(task)
            except RuntimeError as exc:
                local_id = task["local_id"]
                self.outbox.mark_sending(local_id)
                self.outbox.mark_failed(
                    local_id,
                    f"Broker endpoint validation failed: {exc}",
                    max_attempts=1,
                )

        if not approved_tasks:
            return 0

        # Retrieve keys using central environment resolver
        try:
            from app.config.environment import get_env_credential_ref
            hmac_ref = get_env_credential_ref("hmac_secret")
            bearer_ref = get_env_credential_ref("bearer_token")
        except Exception as e:
            log_audit_event("OUTBOX_RETRY_ERROR", "dispatcher", f"Environment configuration error: {e}")
            return 0
        
        hmac_secret = keyring_store.get_secret(hmac_ref)
        bearer_token = keyring_store.get_secret(bearer_ref)
        
        if not hmac_secret or not bearer_token:
            log_audit_event(
                "OUTBOX_RETRY_ERROR", 
                "dispatcher", 
                "Credentials missing from keyring. Retry aborted."
            )
            return 0

        from app.destinations.outbound_payload_builder import refresh_transport_signature
        sent_count = 0
        for task in approved_tasks:
            if should_stop and should_stop():
                break
            local_id = task["local_id"]
            endpoint_url = task["endpoint_url"]
            
            _, json_str, payload_hash, hmac_signature = refresh_transport_signature(
                task["payload_json"],
                hmac_secret
            )
            
            from app.destinations.hmac_signer import create_client_request_headers
            client_key_id = self.settings_manager.get("external_agent.client_key_id") or os.environ.get("CVN_CLIENT_KEY_ID", "default_client_key")
            headers = create_client_request_headers(
                method="POST",
                endpoint_url=endpoint_url,
                raw_body_str=json_str,
                bearer_token=bearer_token,
                hmac_secret=hmac_secret,
                client_key_id=client_key_id,
                nonce=task.get("nonce"),
            )
            
            self.outbox.mark_sending(local_id)
            try:
                response = httpx.post(endpoint_url, content=json_str, headers=headers, timeout=15.0)
                if response.status_code == 200:
                    resp_json = response.json()
                    remote_msg_id = resp_json.get("msg_id") or resp_json.get("task_id")
                    self.outbox.mark_sent(local_id, remote_msg_id)
                    sent_count += 1
                elif response.status_code == 409:
                    self.outbox.mark_duplicate(local_id, response.text)
                    sent_count += 1
                else:
                    self.outbox.mark_failed(local_id, f"HTTP {response.status_code}: {response.text}")
            except Exception as e:
                self.outbox.mark_failed(local_id, str(e))
                
        return sent_count

    def _escape_yaml_value(self, val: Any) -> str:
        if isinstance(val, bool):
            return str(val).lower()
        if isinstance(val, (int, float)):
            return str(val)
        if val is None or val == "":
            return '""'
        
        val_str = str(val)
        # Check if it's a simple alphanumeric string that doesn't need quotes
        if val_str.lower() not in ("true", "false", "null", "yes", "no"):
            import re
            if re.match(r"^[a-zA-Z0-9_\-]+$", val_str):
                return val_str
                
        # String: wrap in quotes and escape internal quotes and backslashes
        escaped = val_str.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _update_note_frontmatter(self, file_path: Path, updates: Dict[str, Any]) -> None:
        """Helper function to update/write frontmatter keys back to local note Markdown file."""
        if not file_path.exists():
            return
        try:
            content = file_path.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            if len(parts) < 3:
                return
            
            yaml_str = parts[1]
            body = parts[2]
            
            lines = yaml_str.splitlines()
            yaml_data: Dict[str, Any] = {}
            current_list_key = None
            
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("-") and current_list_key:
                    val = stripped[1:].strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    if current_list_key not in yaml_data:
                        yaml_data[current_list_key] = []
                    yaml_data[current_list_key].append(val)
                elif ":" in stripped:
                    k, v = stripped.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    if v == "":
                        yaml_data[k] = []
                        current_list_key = k
                    else:
                        if v.lower() == "true":
                            yaml_data[k] = True
                        elif v.lower() == "false":
                            yaml_data[k] = False
                        else:
                            try:
                                if "." in v:
                                    yaml_data[k] = float(v)
                                else:
                                    yaml_data[k] = int(v)
                            except ValueError:
                                yaml_data[k] = v
                        current_list_key = None
                        
            # Update values
            yaml_data.update(updates)
            
            # Re-serialise to yaml block
            new_yaml = ["---"]
            for k, v in yaml_data.items():
                if isinstance(v, list):
                    new_yaml.append(f"{k}:")
                    for item in v:
                        new_yaml.append(f"  - {self._escape_yaml_value(item)}")
                else:
                    new_yaml.append(f"{k}: {self._escape_yaml_value(v)}")
            new_yaml.append("---")
            
            new_content = "\n".join(new_yaml) + body
            file_path.write_text(new_content, encoding="utf-8")
            log_audit_event("MD_FRONTMATTER_UPDATED", "dispatcher", f"Updated frontmatter in {file_path.name}")
        except Exception as e:
            log_audit_event("MD_FRONTMATTER_UPDATE_ERROR", "dispatcher", f"Failed to update note frontmatter: {e}")

    def _update_note_result_block(
        self, 
        file_path: Path, 
        status: str, 
        agent: str, 
        task_id: str, 
        timestamp_str: str, 
        result_summary: str
    ) -> None:
        """Updates or appends the CVN agent result block in the note body in-place."""
        if not file_path.exists():
            return
        
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Format timestamp nicely (e.g. 18 July 2026, 9:27 PM)
            formatted_time = timestamp_str
            try:
                dt = datetime.fromisoformat(timestamp_str)
                formatted_time = dt.strftime("%d %B %Y, %I:%M %p")
            except Exception:
                pass

            # Sanitise result summary to ensure no markdown injection/unsafe chars
            sanitised_result = re.sub(r"[\r\n\t]", " ", result_summary).strip()

            result_block = (
                "<!-- CVN-AGENT-RESULT:START -->\n"
                "## External Agent Result\n\n"
                f"- **Status:** {status.capitalize()}\n"
                f"- **Agent:** {agent.capitalize()}\n"
                f"- **Task ID:** `{task_id}`\n"
                f"- **Completed:** {formatted_time}\n"
                f"- **Result:** {sanitised_result}\n"
                "<!-- CVN-AGENT-RESULT:END -->"
            )

            pattern = re.compile(r"<!-- CVN-AGENT-RESULT:START -->.*?<!-- CVN-AGENT-RESULT:END -->", re.DOTALL)
            if pattern.search(content):
                new_content = pattern.sub(result_block, content)
            else:
                # Append to the end, ensuring proper spacing
                if content.endswith("\n"):
                    new_content = content + "\n" + result_block + "\n"
                else:
                    new_content = content + "\n\n" + result_block + "\n"
            
            file_path.write_text(new_content, encoding="utf-8")
            log_audit_event("MD_RESULT_BLOCK_UPDATED", "dispatcher", f"Updated result block in {file_path.name}")
        except Exception as e:
            log_audit_event("MD_RESULT_BLOCK_UPDATE_ERROR", "dispatcher", f"Failed to update note result block: {e}")

    def check_task_status(self, endpoint_url: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Queries the cvn-status endpoint for a task, returning its status JSON."""
        try:
            from app.config.environment import validate_broker_endpoint
            validate_broker_endpoint(endpoint_url)
        except RuntimeError as exc:
            log_audit_event(
                "STATUS_CHECK_ERROR",
                "dispatcher",
                f"Broker endpoint validation failed for task {task_id}: {exc}",
            )
            return None

        # Retrieve keys
        try:
            from app.config.environment import get_env_credential_ref
            hmac_ref = get_env_credential_ref("hmac_secret")
            bearer_ref = get_env_credential_ref("bearer_token")
        except Exception as e:
            log_audit_event("STATUS_CHECK_ERROR", "dispatcher", f"Environment configuration error: {e}")
            return None

        hmac_secret = keyring_store.get_secret(hmac_ref)
        bearer_token = keyring_store.get_secret(bearer_ref)

        if not hmac_secret or not bearer_token:
            log_audit_event("STATUS_CHECK_ERROR", "dispatcher", "Credentials missing from keyring. Status check aborted.")
            return None

        # Build url: extract base url up to functions/v1
        base_match = re.match(r"(https://[^/]+/functions/v1)", endpoint_url)
        if not base_match:
            log_audit_event("STATUS_CHECK_ERROR", "dispatcher", f"Malformed endpoint URL: {endpoint_url}")
            return None
        
        status_url = f"{base_match.group(1)}/cvn-status/{task_id}"

        import secrets
        now = datetime.now(timezone.utc)
        signed_at_str = now.isoformat()
        nonce = secrets.token_hex(16)

        # Canonical string: GET\n/functions/v1/cvn-status/<task_id>\ntask_id=<task_id>\nsigned_at=<signed_at>\nnonce=<nonce>
        canonical = f"GET\n/functions/v1/cvn-status/{task_id}\ntask_id={task_id}\nsigned_at={signed_at_str}\nnonce={nonce}"
        sig = sign(canonical.encode("utf-8"), hmac_secret)

        try:
            response = httpx.get(
                status_url,
                params={
                    "signed_at": signed_at_str,
                    "nonce": nonce
                },
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "x-cvn-signature": sig
                },
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    return data
                return {"result": str(data)}

            elif response.status_code == 404:
                log_audit_event("STATUS_CHECK_NOT_FOUND", "dispatcher", f"Task {task_id} not found on broker")
                return {"status": "not_found"}
            else:
                log_audit_event("STATUS_CHECK_FAILED", "dispatcher", f"Failed to get status for {task_id}: HTTP {response.status_code}")
                return None
        except Exception as e:
            log_audit_event("STATUS_CHECK_ERROR", "dispatcher", f"HTTP request failed for task {task_id}: {e}")
            return None

    def reconcile_statuses(
        self,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Finds sent/processing tasks and reconciles their status from the remote broker."""
        tasks = self.outbox.get_unfinished_tasks()
        if not tasks:
            return 0

        updated_count = 0
        for task in tasks:
            if should_stop and should_stop():
                break
            local_id = task["local_id"]
            task_id = task["task_id"]
            endpoint_url = task["endpoint_url"]
            note_path = task.get("note_path")
            target_agent = task.get("target_agent")
            if not target_agent:
                try:
                    target_agent = json.loads(task["payload_json"]).get("target_agent")
                except (json.JSONDecodeError, TypeError):
                    target_agent = None
            if target_agent not in ("hermes", "openclaw"):
                target_agent = "openclaw"

            status_data = self.check_task_status(endpoint_url, task_id)
            if not status_data:
                continue

            remote_status = status_data.get("status")
            if not remote_status:
                continue

            # Mapping remote broker status to local status
            local_status = None
            if remote_status == "completed":
                local_status = "completed"
            elif remote_status in ("failed", "cancelled", "dead_letter", "manual_review"):
                local_status = "failed"
            elif remote_status in ("claimed", "running"):
                local_status = "processing"
            elif remote_status == "pending":
                local_status = "sent"

            if local_status and local_status != task["status"]:
                # Update outbox record
                error_msg = status_data.get("error_message") or status_data.get("error_code")
                self.outbox.update_task_status(local_id, local_status, error_msg)
                
                # Update corresponding Obsidian note if note_path is provided
                if note_path:
                    note_file = Path(note_path)
                    if note_file.exists():
                        frontmatter_updates = {
                            "status": local_status,
                            "last_status_check_at": datetime.now().astimezone().isoformat(),
                            "result_summary": status_data.get("result_summary") or "",
                            "error_code": status_data.get("error_code") or ""
                        }
                        if local_status == "completed":
                            frontmatter_updates["completed_at"] = status_data.get("completed_at") or datetime.now().astimezone().isoformat()
                        elif local_status == "failed":
                            frontmatter_updates["failed_at"] = status_data.get("failed_at") or datetime.now().astimezone().isoformat()

                        self._update_note_frontmatter(note_file, frontmatter_updates)
                        
                        # Update note body result block
                        completed_time = status_data.get("completed_at") or status_data.get("failed_at") or datetime.now().astimezone().isoformat()
                        result_text = status_data.get("result_summary") or status_data.get("error_message") or "Task executed."
                        self._update_note_result_block(
                            file_path=note_file,
                            status=local_status,
                            agent=target_agent,
                            task_id=task_id,
                            timestamp_str=completed_time,
                            result_summary=result_text
                        )
                
                updated_count += 1
                
        return updated_count
