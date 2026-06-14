import json
import httpx
from typing import Any, Dict
from app.audit.audit_logger import log_audit_event

class OllamaClassifier:
    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen3.5:latest") -> None:
        self.url = url
        self.model = model

    def classify(self, transcript: str) -> Dict[str, Any]:
        """Calls the local Ollama HTTP API to classify the transcript text into structured categories."""
        log_audit_event("CLASSIFICATION_START", "session", f"Classifying transcript via Ollama model: {self.model}")
        
        prompt = f"""
        Classify this classroom voice note. Respond ONLY with a JSON object.
        JSON format:
        {{
            "category": "student_note" | "behaviour_note" | "maths_note" | "english_note" | "science_note" | "hass_note" | "digitech_note" | "designtech_note" | "reminder" | "email_draft" | "agent_task" | "general_note",
            "sensitivity": "student_sensitive" | "teacher_private" | "non_sensitive",
            "confidence": 0.0 to 1.0
        }}
        
        Category definitions:
        - student_note: general observations or info about a specific student
        - behaviour_note: student behaviour or discipline incidents
        - maths_note: mathematics lessons, activities, or homework
        - english_note: English, reading, spelling, writing, or literature
        - science_note: science lessons, experiments, or activities
        - hass_note: Humanities and Social Sciences (history, geography, civics, first fleet)
        - digitech_note: Digital Technologies (coding, computers, algorithms, pseudocode)
        - designtech_note: Design Technologies (designing, prototypes, engineering, food/material packages)
        - reminder: reminders for the teacher (e.g. print worksheets, prep materials)
        - email_draft: drafts or notes of emails to parents or staff
        - agent_task: direct actions for the AI assistant
        - general_note: other administrative or classroom notes
        
        Transcript: "{transcript}"
        """
        
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }
            
            response = httpx.post(f"{self.url}/api/generate", json=payload, timeout=30.0)
            if response.status_code != 200:
                raise RuntimeError(f"Ollama server returned status code: {response.status_code}")
                
            data = response.json()
            
            # Extract JSON string: check 'response' first, then 'thinking' (for reasoning/thinking models)
            raw_text = data.get("response", "").strip()
            if not raw_text and "thinking" in data:
                raw_text = data.get("thinking", "").strip()
                
            # Clean/extract the JSON substring if the model wrapped it in markdown or conversation
            json_str = raw_text
            start_idx = raw_text.find('{')
            end_idx = raw_text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = raw_text[start_idx:end_idx + 1]
            
            # Parse the structured JSON response
            result: Dict[str, Any] = json.loads(json_str)
            
            # Ensure required keys exist with safe defaults
            if "category" not in result:
                result["category"] = "general_note"
            if "sensitivity" not in result:
                result["sensitivity"] = "teacher_private"
            if "confidence" not in result:
                result["confidence"] = 0.5
                
            log_audit_event(
                "CLASSIFICATION_SUCCESS",
                "session",
                f"Classification result: category={result['category']}, sensitivity={result['sensitivity']}"
            )
            return result
            
        except Exception as e:
            log_audit_event("CLASSIFICATION_ERROR", "session", f"Ollama classification failed: {e}")
            # Fallback to local review queue on error/exception
            return {
                "category": "review_queue",
                "sensitivity": "teacher_private",
                "confidence": 0.0
            }
