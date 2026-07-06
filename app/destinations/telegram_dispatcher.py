import time
import httpx
from pathlib import Path
from datetime import datetime
from typing import Any, Dict
from app.audit.audit_logger import log_audit_event

class TelegramDispatcher:
    def __init__(self, settings_manager: Any) -> None:
        self.settings_manager = settings_manager

    def resolve_agent(self, transcript: str, classification_data: Dict[str, Any]) -> str:
        """Determines the target agent (hermes or openclaw) based on keywords, classification, or settings."""
        transcript_lower = transcript.lower()
        
        # 1. Check keywords in the transcript first
        if "openclaw" in transcript_lower or "open claw" in transcript_lower:
            return "openclaw"
        if "hermes" in transcript_lower:
            return "hermes"
            
        # 2. Check LLM suggestion
        agent_target = classification_data.get("agent_target")
        if agent_target in ("hermes", "openclaw"):
            return agent_target
            
        # 3. Fallback to settings manager default agent
        default_agent = self.settings_manager.get("agents.default_agent") or "hermes"
        return default_agent

    def format_message(self, task_id: str, transcript: str, category: str) -> str:
        """Formats the task details into a structured Telegram message."""
        now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
        return (
            f"📋 *Agent Task* `[{task_id}]`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{transcript}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Priority*: normal\n"
            f"🕐 *Sent*: {now_str}\n"
            f"📂 *Category*: {category}\n"
            f"🏷️ *Source*: Classroom Voice Notes"
        )

    def send_raw_message(self, message: str, agent: str = "hermes") -> bool:
        """Sends a raw text message to a specific agent's Telegram chat.
        
        Includes retry logic (2 retries with 3s delays).
        """
        token = self.settings_manager.get("agents.telegram_token")
        if not token:
            log_audit_event("TELEGRAM_RAW_SEND_FAILED", "telegram", "Bot token is missing.")
            return False
            
        chat_id = self.settings_manager.get(f"agents.agents.{agent}.chat_id")
        if not chat_id:
            log_audit_event("TELEGRAM_RAW_SEND_FAILED", "telegram", f"Chat ID for agent '{agent}' is missing.")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = httpx.post(url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    log_audit_event("TELEGRAM_RAW_SEND_SUCCESS", "telegram", f"Raw message successfully sent to {agent}")
                    return True
                else:
                    raise RuntimeError(f"Server returned status {response.status_code}: {response.text}")
            except Exception as e:
                log_audit_event("TELEGRAM_RAW_SEND_RETRY", "telegram", f"Send failed (attempt {attempt+1}): {e}")
                if attempt < max_retries:
                    time.sleep(3.0)
        return False

    def dispatch(self, transcript: str, classification_data: Dict[str, Any], note_path: str) -> bool:
        """Resolves target agent, formats the structured message, and sends it via the Telegram Bot API.
        
        Includes retry logic (2 retries with 3s delays) and updates local frontmatter.
        """
        token = self.settings_manager.get("agents.telegram_token")
        if not token:
            log_audit_event("TELEGRAM_DISPATCH_FAILED", "telegram", "Bot token is missing.")
            return False

        agent = self.resolve_agent(transcript, classification_data)
        chat_id = self.settings_manager.get(f"agents.agents.{agent}.chat_id")
        
        if not chat_id:
            log_audit_event("TELEGRAM_DISPATCH_FAILED", "telegram", f"Chat ID for agent '{agent}' is missing.")
            return False

        task_id = f"CVN-{int(time.time())}"
        message = self.format_message(task_id, transcript, classification_data.get("category", "agent_task"))
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }

        success = False
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = httpx.post(url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    log_audit_event("TELEGRAM_DISPATCH_SUCCESS", "telegram", f"Task {task_id} successfully sent to {agent} (chat: {chat_id})")
                    success = True
                    break
                else:
                    raise RuntimeError(f"Server returned status {response.status_code}: {response.text}")
            except Exception as e:
                log_audit_event("TELEGRAM_DISPATCH_RETRY", "telegram", f"Send failed (attempt {attempt+1}): {e}")
                if attempt < max_retries:
                    time.sleep(3.0)

        if success:
            # Update note frontmatter in Obsidian
            updates = {
                "status": "sent",
                "task_id": task_id,
                "agent_target": agent,
                "sent_at": datetime.now().isoformat()
            }
            self._update_note_frontmatter(Path(note_path), updates)
            return True
        else:
            log_audit_event("TELEGRAM_DISPATCH_ERROR", "telegram", f"Failed to send task {task_id} after {max_retries+1} attempts.")
            # Record dead-letter event or update note to show failed dispatch
            self._update_note_frontmatter(Path(note_path), {"status": "dispatch_failed"})
            return False

    def _update_note_frontmatter(self, file_path: Path, updates: Dict[str, Any]) -> None:
        """Safely parses, updates, and rewrites the frontmatter block of the Obsidian Markdown note."""
        if not file_path.exists():
            return
        try:
            content = file_path.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            if len(parts) < 3:
                return
            
            yaml_str = parts[1]
            body = parts[2]
            
            # Parse current yaml lines
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
                        
            # Apply updates
            yaml_data.update(updates)
            
            # Re-build yaml block
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
            log_audit_event("MD_FRONTMATTER_UPDATED", "telegram", f"Updated frontmatter in {file_path.name}")
        except Exception as e:
            log_audit_event("MD_FRONTMATTER_UPDATE_ERROR", "telegram", f"Failed to update note frontmatter: {e}")
