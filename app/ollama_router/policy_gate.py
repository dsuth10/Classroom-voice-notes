import re
import urllib.parse
from typing import Any, Dict, List, Tuple, Optional
from app.audit.audit_logger import log_audit_event
from app.privacy.student_registry import StudentRegistry

class PolicyGate:
    def is_telegram_allowed(self, sensitivity: str, category: str, transcript: str) -> bool:
        """Determines if a note is permitted to route to external Telegram.
        
        Enforces local-first rules: sensitive student/teacher details are strictly local.
        """
        # Rely purely on the local LLM's classification of sensitivity
        # Any category other than non_sensitive is blocked from external transmission
        if sensitivity in ("student_sensitive", "teacher_private"):
            log_audit_event("POLICY_BLOCKED", "session", "Note marked sensitive; external routing blocked.")
            return False
            
        # Even if marked non_sensitive, only allow specific agent task routes
        if category != "agent_task":
            log_audit_event("POLICY_BLOCKED", "session", f"Category '{category}' is local-only; external routing blocked.")
            return False
            
        log_audit_event("POLICY_APPROVED", "session", "Note approved for external transmission.")
        return True

    def is_external_dispatch_allowed(
        self,
        category: str,
        sensitivity: str,
        safe_task: Optional[Dict[str, Any]],
        transcript: str,
        payload: Dict[str, Any],
        source_device_id: str,
        target_agent: str,
        endpoint_url: str,
        vault_path: str,
        config: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """Validates all safety policy rules for the external broker queue.
        
        Returns:
            (allowed, checks_passed_list)
        """
        checks_passed: List[str] = []
        
        # 1. Category must be agent_task
        if category != "agent_task":
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Category '{category}' is local-only.")
            return False, checks_passed
        checks_passed.append("category_agent_task")
        
        # 2. Sensitivity must be non_sensitive
        if sensitivity != "non_sensitive":
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Sensitivity '{sensitivity}' is restricted.")
            return False, checks_passed
        checks_passed.append("sensitivity_non_sensitive")
        
        # 3. Safe external task structure validation
        if not safe_task or not isinstance(safe_task, dict):
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Safe external task structure is missing.")
            return False, checks_passed
            
        task_data = payload.get("task", {})
        title = task_data.get("title", "").strip()
        instructions = task_data.get("instructions", "").strip()
        if not title or not instructions:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Safe external task has empty title or instructions.")
            return False, checks_passed
        checks_passed.append("safe_external_task_exists")
        
        # 4. Student registry loaded successfully
        from pathlib import Path
        if not vault_path or not Path(vault_path).exists():
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Vault path is empty or does not exist. Registry cannot be loaded.")
            return False, checks_passed
            
        try:
            registry = StudentRegistry(vault_path)
            if not hasattr(registry, "data") or not isinstance(registry.data, dict) or "students" not in registry.data:
                raise ValueError("Registry data format invalid.")
        except Exception as e:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Failed to load student registry: {e}")
            return False, checks_passed
        checks_passed.append("student_registry_loaded")
        
        # 5. Check for student names in transcript and payload task fields (word boundaries, normalized case)
        students = registry.data.get("students", {})
        student_names = []
        for key, entry in students.items():
            if isinstance(entry, dict) and "display_name" in entry:
                student_names.append(entry["display_name"])
            else:
                student_names.append(key)
                
        # Text fields to scan
        fields_to_scan = [transcript, title, instructions]
        for student_name in student_names:
            name_clean = student_name.strip()
            if not name_clean:
                continue
            
            # Match word boundary with flexible whitespace support for multi-word names
            escaped_name = re.escape(name_clean.lower())
            flexible_space_name = escaped_name.replace(r"\ ", r"\s+").replace(" ", r"\s+")
            pattern_str = r"(?<![A-Za-z])" + flexible_space_name + r"(?![A-Za-z])"
            pattern = re.compile(pattern_str, re.IGNORECASE)
            
            for text in fields_to_scan:
                if pattern.search(text):
                    log_audit_event(
                        "POLICY_BLOCKED", 
                        "policy_gate", 
                        f"Student name match detected ('{name_clean}') in outgoing task metadata."
                    )
                    return False, checks_passed
        checks_passed.append("no_student_registry_match")
        
        # 6. Check for forbidden keywords (welfare, medical, absence, behaviour, etc.)
        forbidden_terms = [
            "welfare", "medical", "absence", "behaviour", "behavior", "pickup", "custody",
            "iep", "suspension", "incident", "counselling", "counseling", "psychologist",
            "injury", "illness", "allergic", "allergy", "medication", "cps", "safety plan"
        ]
        for term in forbidden_terms:
            pattern_str = r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])"
            pattern = re.compile(pattern_str, re.IGNORECASE)
            for text in [title, instructions]:
                if pattern.search(text):
                    log_audit_event(
                        "POLICY_BLOCKED", 
                        "policy_gate", 
                        f"Forbidden keyword match detected ('{term}') in outgoing task metadata."
                    )
                    return False, checks_passed
        checks_passed.append("no_forbidden_terms")
        
        # 7. Check no audio attached
        # Ensure no filenames ending with extensions or containing audio markers are in task title/instructions
        audio_extensions = [r"\.wav", r"\.mp3", r"\.m4a", r"\.aac", r"\.flac", r"\.ogg"]
        for ext in audio_extensions:
            pattern = re.compile(ext, re.IGNORECASE)
            for text in [title, instructions]:
                if pattern.search(text):
                    log_audit_event("POLICY_BLOCKED", "policy_gate", "Audio file extension found in task payload.")
                    return False, checks_passed
        checks_passed.append("no_audio_attached")
        
        # 8. Check no local file paths
        local_path_patterns = [
            r"[A-Za-z]:\\", r"[A-Za-z]:/",  # Drive letters
            r"\\\\",                         # UNC shares
            r"\\Users\\", r"/Users/",        # Profile paths
            r"\\AppData\\", r"/AppData/",    # AppData paths
            r"\.obsidian"                    # Obsidian config
        ]
        for pattern_str in local_path_patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            for text in [title, instructions]:
                if pattern.search(text):
                    log_audit_event("POLICY_BLOCKED", "policy_gate", f"Local path signature '{pattern_str}' found in payload.")
                    return False, checks_passed
        checks_passed.append("no_local_file_path")
        
        # 9. Check no raw transcript in payload
        transcript_clean = transcript.strip().lower()
        if transcript_clean:
            if transcript_clean in title.lower() or transcript_clean in instructions.lower():
                log_audit_event("POLICY_BLOCKED", "policy_gate", "Raw transcript detected inside outgoing task payload.")
                return False, checks_passed
        checks_passed.append("no_raw_transcript")
        
        # 10. Check no parent contact details (basic phone/email regex checks)
        email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
        phone_pattern = re.compile(r"\b\d{8,15}\b")  # Sequence of 8-15 digits representing phone number
        for text in [title, instructions]:
            if email_pattern.search(text) or phone_pattern.search(text):
                log_audit_event("POLICY_BLOCKED", "policy_gate", "Parent or user contact detail pattern detected in payload.")
                return False, checks_passed
        checks_passed.append("no_parent_contact")
        
        # 11. Check payload size under limit
        max_bytes = config.get("max_payload_bytes") or 65536
        import json
        payload_bytes = json.dumps(payload).encode("utf-8")
        if len(payload_bytes) > max_bytes:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Payload size ({len(payload_bytes)} bytes) exceeds limit ({max_bytes}).")
            return False, checks_passed
        checks_passed.append("payload_size_ok")
        
        # 12. Check source_device_id present
        if not source_device_id or not source_device_id.strip():
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Missing source_device_id.")
            return False, checks_passed
        checks_passed.append("source_device_id_present")
        
        # 13. Check target_agent is allowlisted
        allowed_agents = config.get("allowed_target_agents") or ["hermes", "openclaw", "auto"]
        if target_agent not in allowed_agents:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Unapproved target agent '{target_agent}'.")
            return False, checks_passed
        checks_passed.append("target_agent_allowlisted")
        
        # 14. Check endpoint domain is allowlisted
        allowed_domains = config.get("allowed_endpoint_domains") or ["supabase.co"]
        try:
            parsed = urllib.parse.urlparse(endpoint_url)
            netloc = parsed.netloc or parsed.path  # fallback if url lacks scheme
            domain = netloc.split(":")[0]          # strip port if present
            
            domain_matched = False
            for allowed in allowed_domains:
                if domain == allowed or domain.endswith("." + allowed):
                    domain_matched = True
                    break
            if not domain_matched:
                log_audit_event("POLICY_BLOCKED", "policy_gate", f"Endpoint domain '{domain}' is not allowlisted.")
                return False, checks_passed
        except Exception as e:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Invalid endpoint URL schema: {e}")
            return False, checks_passed
        checks_passed.append("endpoint_domain_allowlisted")
        
        # All checks passed successfully!
        log_audit_event("POLICY_APPROVED", "policy_gate", "External dispatch payload passed all Policy Gate requirements.")
        return True, checks_passed
