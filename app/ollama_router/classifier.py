import json
import httpx
import re
import time
from typing import Any, Dict
from app.audit.audit_logger import log_audit_event
from app.config.settings import is_loopback_url

class OllamaClassifier:
    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen3.5:latest") -> None:
        if not is_loopback_url(url):
            log_audit_event("SECURITY_ERROR", "classifier", f"Attempted to configure non-loopback Ollama URL: {url}")
            raise ValueError(f"Ollama URL must point to local loopback (localhost, 127.0.0.1, ::1). Got: {url}")
        self.url = url
        self.model = model

    def classify(self, transcript: str, recorded_at: str = "", duration_seconds: int = 0) -> Dict[str, Any]:
        """Calls the local Ollama HTTP API to classify the transcript text into structured categories."""
        if not is_loopback_url(self.url):
            log_audit_event("SECURITY_ERROR", "classifier", f"Refusing classification with non-loopback Ollama URL: {self.url}")
            raise ValueError(f"Ollama URL must point to local loopback (localhost, 127.0.0.1, ::1). Got: {self.url}")
        log_audit_event("CLASSIFICATION_START", "session", f"Classifying transcript via Ollama model: {self.model}")

        
        prompt = f"""
        You are a local routing classifier for a teacher voice-note application.
        Your job is to classify a transcript and return strict JSON only.

        Hard rules:
        - Student names, student achievement, behaviour, welfare, absence, pickup, family, medical, emotional, support or assessment information must stay local.
        - If the transcript may contain student-sensitive information, telegram_allowed must be false.
        - If the transcript asks an agent to perform research, planning, communication, automation, software, file, calendar, email, or other professional work and contains no student-sensitive information, route it to telegram_agent_task with category agent_task.
        - Distinguish drafting from acting: "draft an email" is email_draft and requires review; "send an email" is an agent_task whose task instructions explicitly say to send it.
        - For every agent_task, return a self-contained task object with a short title, executable instructions, and priority. Preserve exact requested literals, recipients expressed as safe aliases such as "me", dates, success criteria, and the exact phrase "CONFIRM ACTION" when spoken. Do not copy the whole raw transcript or include student information, contact details, local paths, or audio paths.
        - If uncertain, route to review_queue.
        - Do not invent facts.
        - Do not send normal classroom notes externally.
        - Return JSON only.
        
        JSON format:
        {{
            "route": "local_obsidian" | "local_student_note" | "local_reminder" | "telegram_agent_task" | "email_draft" | "review_queue" | "discard_cancelled",
            "sensitivity": "student_sensitive" | "teacher_private" | "non_sensitive" | "school_sensitive" | "unknown",
            "category": "student_note" | "behaviour_note" | "maths_note" | "english_note" | "science_note" | "hass_note" | "digitech_note" | "designtech_note" | "reminder" | "email_draft" | "agent_task" | "general_note" | "unknown",
            "title": "<short descriptive title>",
            "summary": "<1 sentence summary>",
            "contains_student_information": <bool>,
            "contains_external_task": <bool>,
            "telegram_allowed": <bool>,
            "requires_review": <bool>,
            "recommended_destination": "<recommended folder or service>",
            "reminder_time": "<YYYY-MM-DD HH:MM:SS or null>",
            "tags": ["<tag1>", "<tag2>"],
            "confidence": <0.0 to 1.0>,
            "agent_target": "hermes" | "openclaw" | "auto" | null,
            "task": {{
                "title": "<short action title>",
                "instructions": "<self-contained instructions for the agent>",
                "priority": "low" | "normal" | "high"
            }} or null,
            "category_fields": {{
                "students_mentioned": ["<first name 1>", "<first name 2>"] or [],
                "strand": "<Australian Curriculum v9 Strand name or null>",
                "misconception_type": "<description of maths misconception or null>",
                "behaviour_type": "<disruption|positive|welfare|safety|academic|null>",
                "action_taken": "<description of action e.g. verbal warning|parent contact|null>",
                "observation_type": "<academic progress|general observation|wellbeing|null>",
                "year_level": "<e.g. Year 5|Year 6|null>",
                "investigation_type": "<type of science investigation or null>",
                "text_type": "<type of english text studied e.g. persuasive|narrative|null>",
                "recipient": "<intended recipient name/email or null>",
                "subject_line": "<suggested subject line for email or null>",
                "priority": "<low|normal|high|null>"
            }}
        }}

        Agent Target Guidance:
        - Set to "hermes" if the transcript explicitly mentions "Hermes" or if it is a general planning, research, or instructional content request.
        - Set to "openclaw" if the transcript explicitly mentions "OpenClaw" or asks for code generation, software development, data parsing, or direct analytical processing.
        - Set to "auto" if it is an agent task but no specific agent is named.
        - Set to null if it is not an agent task.

        Category Fields Guidance:
        - Populate `students_mentioned` with student first names mentioned in the text.
        - Populate curriculum fields (strand, year_level, misconception_type, etc.) only if category relates to a subject note.
        - Set unused/irrelevant fields within `category_fields` to null.
        
        Context:
        - Recorded at: {recorded_at}
        - Duration: {duration_seconds} seconds
        
        Transcript: "{transcript}"
        """
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = httpx.post(f"{self.url}/api/generate", json=payload, timeout=30.0)
                if response.status_code != 200:
                    raise RuntimeError(f"Ollama server returned status code: {response.status_code}")
                    
                data = response.json()
                
                # Extract JSON string: check 'response' first, then 'thinking'
                raw_text = data.get("response", "").strip()
                if not raw_text and "thinking" in data:
                    raw_text = data.get("thinking", "").strip()
                    
                json_str = raw_text
                start_idx = raw_text.find('{')
                end_idx = raw_text.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_str = raw_text[start_idx:end_idx + 1]
                
                result: Dict[str, Any] = json.loads(json_str)
                
                # Ensure required keys exist with safe defaults
                if "category" not in result:
                    result["category"] = "general_note"
                if "sensitivity" not in result:
                    result["sensitivity"] = "teacher_private"
                if "confidence" not in result:
                    result["confidence"] = 0.5
                if "route" not in result:
                    result["route"] = "local_obsidian"
                if "telegram_allowed" not in result:
                    result["telegram_allowed"] = False
                if "agent_target" not in result:
                    result["agent_target"] = "auto" if result.get("category") == "agent_task" else None
                if result.get("category") == "agent_task":
                    task = result.get("task")
                    if not isinstance(task, dict):
                        task = {}

                    task_title = str(task.get("title") or result.get("title") or "Agent task").strip()
                    task_instructions = str(
                        task.get("instructions") or result.get("summary") or ""
                    ).strip()
                    task_instructions = self._repair_explicit_email_action(
                        transcript,
                        result.get("category_fields"),
                        task_instructions,
                    )
                    task_priority = str(task.get("priority") or "normal").strip().lower()
                    if task_priority not in {"low", "normal", "high"}:
                        task_priority = "normal"

                    result["task"] = {
                        "title": task_title,
                        "instructions": task_instructions,
                        "priority": task_priority,
                    }
                else:
                    result["task"] = None
                if "category_fields" not in result or not isinstance(result["category_fields"], dict):
                    result["category_fields"] = {}
                    
                log_audit_event(
                    "CLASSIFICATION_SUCCESS",
                    "session",
                    f"Classification result: category={result['category']}, sensitivity={result['sensitivity']}, agent_target={result.get('agent_target')}"
                )
                return result
                
            except Exception as e:
                log_audit_event("CLASSIFICATION_ERROR", "session", f"Ollama classification failed (attempt {attempt+1}): {e}")
                if attempt < max_retries:
                    time.sleep(2)
                else:
                    return {
                        "category": "review_queue",
                        "route": "review_queue",
                        "sensitivity": "unknown",
                        "confidence": 0.0,
                        "title": "Unclassified Note",
                        "summary": "Classification failed.",
                        "telegram_allowed": False,
                        "agent_target": None,
                        "category_fields": {}
                    }
        
        return {
            "category": "review_queue",
            "route": "review_queue",
            "sensitivity": "unknown",
            "confidence": 0.0,
            "telegram_allowed": False,
            "agent_target": None,
            "category_fields": {}
        }

    @staticmethod
    def _repair_explicit_email_action(
        transcript: str,
        category_fields: Any,
        model_instructions: str,
    ) -> str:
        """Preserve explicit owner-email commands when a local model paraphrases them.

        This narrow repair deliberately applies only to send-email requests addressed
        to the safe owner aliases ``me`` or ``myself``. It keeps authorization separate
        from message content so a spoken confirmation cannot be swallowed into the body.
        """
        normalized = " ".join(str(transcript).split())
        if not re.search(r"\bsend\b.*\bemail\b", normalized, flags=re.IGNORECASE):
            return model_instructions

        fields = category_fields if isinstance(category_fields, dict) else {}
        field_recipient = str(fields.get("recipient") or "").strip().lower()
        owner_recipient = field_recipient in {"me", "myself"} or bool(
            re.search(r"\bemail\s+to\s+(?:me|myself)\b", normalized, flags=re.IGNORECASE)
        )
        if not owner_recipient:
            return model_instructions

        has_confirmation = bool(
            re.search(r"\bconfirm\s+action\b", normalized, flags=re.IGNORECASE)
        )
        model_kept_owner = bool(
            re.search(r"\bemail\s+to\s+(?:me|myself)\b", model_instructions, flags=re.IGNORECASE)
        )
        if model_kept_owner and not has_confirmation:
            return model_instructions

        subject_match = re.search(
            r"\bwith\s+subjects?\s+(.+?)\s+and\s+(?:the\s+)?body\s+",
            normalized,
            flags=re.IGNORECASE,
        )
        body_match = re.search(
            r"\band\s+(?:the\s+)?body\s+(.+?)(?=\s+confirm\s+action\b|\s+save\b|$)",
            normalized,
            flags=re.IGNORECASE,
        )
        subject = (
            subject_match.group(1).strip(" .,:;\"'")
            if subject_match
            else str(fields.get("subject_line") or "").strip()
        )
        body = body_match.group(1).strip(" .,:;\"'") if body_match else ""

        # Only reconstruct when both user-authored message fields are available.
        if not subject or not body:
            return model_instructions

        repaired = (
            f"Send an email to me with subject {json.dumps(subject, ensure_ascii=False)} "
            f"and body {json.dumps(body, ensure_ascii=False)}."
        )
        if has_confirmation:
            repaired += "\n\nCONFIRM ACTION"
        return repaired
