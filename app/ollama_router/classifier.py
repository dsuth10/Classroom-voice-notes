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
            "category": "student_note" | "behaviour_note" | "maths_note" | "reminder" | "email_draft" | "agent_task" | "general_note",
            "sensitivity": "student_sensitive" | "teacher_private" | "non_sensitive",
            "confidence": 0.0 to 1.0
        }}
        
        Transcript: "{transcript}"
        """
        
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }
            
            response = httpx.post(f"{self.url}/api/generate", json=payload, timeout=10.0)
            if response.status_code != 200:
                raise RuntimeError(f"Ollama server returned status code: {response.status_code}")
                
            data = response.json()
            raw_text = data.get("response", "").strip()
            
            # Parse the structured JSON response
            result: Dict[str, Any] = json.loads(raw_text)
            
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
