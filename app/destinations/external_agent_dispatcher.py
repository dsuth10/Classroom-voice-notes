import httpx
import platform
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

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
            
        default_agent = self.settings_manager.get("external_agent.target_agent_default") or "hermes"
        return str(default_agent)

    def dispatch(self, classification_data: Dict[str, Any], note_path: str, transcript: str = "") -> bool:
        """Validates external routing policy, signs the payload, enqueues, and transmits it."""
        # 1. Check if disabled globally
        enabled = self.settings_manager.get("external_agent.enabled")
        if not enabled:
            log_audit_event("EXTERNAL_DISPATCH_DISABLED", "dispatcher", "External agent dispatch is disabled in settings.")
            return False

        # 2. Check credentials exist
        hmac_ref = self.settings_manager.get("external_agent.hmac_secret_ref") or "cvn_hmac_secret"
        bearer_ref = self.settings_manager.get("external_agent.bearer_token_ref") or "cvn_bearer_token"
        
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

        # 7. HMAC Sign
        hmac_signature = sign(json_str.encode("utf-8"), hmac_secret)

        # 8. Enqueue locally in pending state
        local_id = self.outbox.enqueue(
            task_id=payload["task_id"],
            endpoint_url=endpoint_url,
            payload_json=json_str,
            payload_hash=payload_hash,
            idempotency_key=payload["idempotency_key"],
            nonce=payload["nonce"]
        )

        # 9. Perform HTTP POST request
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "x-cvn-signature": hmac_signature,
            "Content-Type": "application/json"
        }

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
                    "sent_at": datetime.now().isoformat()
                })
                return True
            elif response.status_code == 409:
                self.outbox.mark_duplicate(local_id, response.text)
                self._update_note_frontmatter(Path(note_path), {
                    "status": "sent",
                    "task_id": payload["task_id"],
                    "agent_target": target_agent,
                    "sent_at": datetime.now().isoformat()
                })
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

    def retry_pending(self) -> int:
        """Retries all pending tasks in the outbox that are past their next_retry_at time."""
        pending_tasks = self.outbox.get_pending()
        if not pending_tasks:
            return 0

        # Retrieve keys
        hmac_ref = self.settings_manager.get("external_agent.hmac_secret_ref") or "cvn_hmac_secret"
        bearer_ref = self.settings_manager.get("external_agent.bearer_token_ref") or "cvn_bearer_token"
        
        hmac_secret = keyring_store.get_secret(hmac_ref)
        bearer_token = keyring_store.get_secret(bearer_ref)
        
        if not hmac_secret or not bearer_token:
            log_audit_event(
                "OUTBOX_RETRY_ERROR", 
                "dispatcher", 
                "Credentials missing from keyring. Retry aborted."
            )
            return 0

        sent_count = 0
        for task in pending_tasks:
            local_id = task["local_id"]
            endpoint_url = task["endpoint_url"]
            json_str = task["payload_json"]
            
            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "x-cvn-signature": sign(json_str.encode("utf-8"), hmac_secret),
                "Content-Type": "application/json"
            }
            
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
            
            # Simple line-by-line key/value yaml parsing
            lines = yaml_str.splitlines()
            yaml_data: Dict[str, Any] = {}
            current_list_key = None
            
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("-") and current_list_key:
                    if current_list_key not in yaml_data:
                        yaml_data[current_list_key] = []
                    yaml_data[current_list_key].append(stripped[1:].strip())
                elif ":" in stripped:
                    k, v = stripped.split(":", 1)
                    k = k.strip()
                    v = v.strip()
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
                        new_yaml.append(f"  - {item}")
                elif isinstance(v, bool):
                    new_yaml.append(f"{k}: {str(v).lower()}")
                else:
                    new_yaml.append(f"{k}: {v}")
            new_yaml.append("---")
            
            new_content = "\n".join(new_yaml) + body
            file_path.write_text(new_content, encoding="utf-8")
            log_audit_event("MD_FRONTMATTER_UPDATED", "dispatcher", f"Updated frontmatter in {file_path.name}")
        except Exception as e:
            log_audit_event("MD_FRONTMATTER_UPDATE_ERROR", "dispatcher", f"Failed to update note frontmatter: {e}")
