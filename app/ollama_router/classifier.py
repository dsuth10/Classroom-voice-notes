import json
import httpx
import time
from typing import Any, Dict
from app.audit.audit_logger import log_audit_event

class OllamaClassifier:
    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen3.5:latest") -> None:
        self.url = url
        self.model = model

    def classify(self, transcript: str, recorded_at: str = "", duration_seconds: int = 0) -> Dict[str, Any]:
        """Calls the local Ollama HTTP API to classify the transcript text into structured categories."""
        log_audit_event("CLASSIFICATION_START", "session", f"Classifying transcript via Ollama model: {self.model}")
        
        prompt = f"""
        You are a local routing classifier for a teacher voice-note application.
        Your job is to classify a transcript and return strict JSON only.

        Hard rules:
        - Student names, student achievement, behaviour, welfare, absence, pickup, family, medical, emotional, support or assessment information must stay local.
        - If the transcript may contain student-sensitive information, telegram_allowed must be false.
        - If the transcript asks for research, planning, or general professional work and contains no student-sensitive information, it may be routed to telegram_agent_task.
        - If the transcript asks to email or contact someone, route to email_draft and require review.
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
