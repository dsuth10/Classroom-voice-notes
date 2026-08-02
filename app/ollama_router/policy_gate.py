import re
import urllib.parse
from typing import Any, Dict, List, Tuple, Optional
from app.audit.audit_logger import log_audit_event
from app.privacy.student_registry import StudentRegistry
from app.privacy.outbound_assessment import OutboundAssessment

class PolicyGate:
    def is_telegram_allowed(self, sensitivity: str, category: str, transcript: str) -> bool:
        """Determines if a note is permitted to route to external Telegram.
        
        Enforces local-first rules: sensitive student/teacher details are strictly local.
        """
        if sensitivity in ("student_sensitive", "teacher_private"):
            log_audit_event("POLICY_BLOCKED", "session", "Note marked sensitive; external routing blocked.")
            return False
            
        if category != "agent_task":
            log_audit_event("POLICY_BLOCKED", "session", f"Category '{category}' is local-only; external routing blocked.")
            return False
            
        log_audit_event("POLICY_APPROVED", "session", "Note approved for external transmission.")
        return True

    def assess_outbound(
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
    ) -> OutboundAssessment:
        """Evaluates all privacy and security policy rules, returning a structured OutboundAssessment."""
        checks_passed: List[str] = []
        findings: List[str] = []
        suggested_redactions: List[str] = []
        high_risk_flags: List[str] = []
        
        # 1. Category must be agent_task
        if category != "agent_task":
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Category '{category}' is local-only.")
            findings.append("category_not_agent_task")
        else:
            checks_passed.append("category_agent_task")
            
        # 2. Sensitivity check
        if sensitivity != "non_sensitive":
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Sensitivity '{sensitivity}' is restricted.")
            findings.append(f"sensitivity_{sensitivity}")
            high_risk_flags.append("sensitivity_restricted")
        else:
            checks_passed.append("sensitivity_non_sensitive")
            
        # 3. Safe task structure check
        task_data = payload.get("task", {}) if isinstance(payload, dict) else {}
        title = task_data.get("title", "").strip()
        instructions = task_data.get("instructions", "").strip()
        
        if not safe_task or not isinstance(safe_task, dict) or not title or not instructions:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Safe external task structure is missing or incomplete.")
            findings.append("safe_external_task_invalid")
        else:
            checks_passed.append("safe_external_task_exists")
            
        # 4. Student registry load and match check
        registry_loaded = False
        from pathlib import Path
        if vault_path and Path(vault_path).exists():
            try:
                registry = StudentRegistry(vault_path)
                if hasattr(registry, "data") and isinstance(registry.data, dict) and "students" in registry.data:
                    registry_loaded = True
            except Exception as e:
                log_audit_event("POLICY_BLOCKED", "policy_gate", f"Failed to load student registry: {e}")
        
        if not registry_loaded:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Student registry loading failed.")
            findings.append("student_registry_unavailable")
        else:
            checks_passed.append("student_registry_loaded")
            
            # Scan for student names
            students = registry.data.get("students", {})
            student_names = []
            for key, entry in students.items():
                if isinstance(entry, dict) and "display_name" in entry:
                    student_names.append(entry["display_name"])
                else:
                    student_names.append(key)
                    
            fields_to_scan = [transcript, title, instructions]
            name_matched = False
            for student_name in student_names:
                name_clean = student_name.strip()
                if not name_clean:
                    continue
                escaped_name = re.escape(name_clean.lower())
                flexible_space_name = escaped_name.replace(r"\ ", r"\s+").replace(" ", r"\s+")
                pattern_str = r"(?<![A-Za-z])" + flexible_space_name + r"(?![A-Za-z])"
                pattern = re.compile(pattern_str, re.IGNORECASE)
                for text in fields_to_scan:
                    if pattern.search(text):
                        name_matched = True
                        suggested_redactions.append(f"Remove or anonymise student name '{name_clean}'")
                        break
                if name_matched:
                    break
                    
            if name_matched:
                log_audit_event("POLICY_BLOCKED", "policy_gate", "Student name match detected in outgoing metadata.")
                findings.append("student_name_match")
                high_risk_flags.append("student_name_match")
            else:
                checks_passed.append("no_student_registry_match")
                
        # 5. Forbidden keywords check
        forbidden_terms = [
            "welfare", "medical", "absence", "behaviour", "behavior", "pickup", "custody",
            "iep", "suspension", "incident", "counselling", "counseling", "psychologist",
            "injury", "illness", "allergic", "allergy", "medication", "cps", "safety plan"
        ]
        forbidden_matched = False
        for term in forbidden_terms:
            pattern_str = r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])"
            pattern = re.compile(pattern_str, re.IGNORECASE)
            for text in [title, instructions]:
                if pattern.search(text):
                    forbidden_matched = True
                    suggested_redactions.append(f"Remove sensitive term '{term}'")
                    break
            if forbidden_matched:
                break
                
        if forbidden_matched:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Forbidden keyword match detected.")
            findings.append("forbidden_keyword_match")
            high_risk_flags.append("forbidden_keyword_match")
        else:
            checks_passed.append("no_forbidden_terms")
            
        # 6. Audio extensions check
        audio_extensions = [r"\.wav", r"\.mp3", r"\.m4a", r"\.aac", r"\.flac", r"\.ogg"]
        audio_matched = False
        for ext in audio_extensions:
            pattern = re.compile(ext, re.IGNORECASE)
            for text in [title, instructions]:
                if pattern.search(text):
                    audio_matched = True
                    break
            if audio_matched:
                break
                
        if audio_matched:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Audio file extension found in payload.")
            findings.append("audio_extension_found")
        else:
            checks_passed.append("no_audio_attached")
            
        # 7. Local file paths check
        local_path_patterns = [
            r"[A-Za-z]:\\", r"[A-Za-z]:/",
            r"\\\\",
            r"\\Users\\", r"/Users/",
            r"\\AppData\\", r"/AppData/",
            r"\.obsidian"
        ]
        path_matched = False
        for pattern_str in local_path_patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            for text in [title, instructions]:
                if pattern.search(text):
                    path_matched = True
                    break
            if path_matched:
                break
                
        if path_matched:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Local path signature found in payload.")
            findings.append("local_path_found")
        else:
            checks_passed.append("no_local_file_path")
            
        # 8. Raw transcript leakage check
        transcript_clean = transcript.strip().lower()
        transcript_matched = False
        if transcript_clean and (transcript_clean in title.lower() or transcript_clean in instructions.lower()):
            transcript_matched = True
            
        if transcript_matched:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Raw transcript detected inside outgoing task payload.")
            findings.append("raw_transcript_in_payload")
            high_risk_flags.append("raw_transcript_in_payload")
        else:
            checks_passed.append("no_raw_transcript")
            
        # 9. Parent contact details check
        email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
        phone_pattern = re.compile(r"\b\d{8,15}\b")
        contact_matched = False
        for text in [title, instructions]:
            if email_pattern.search(text) or phone_pattern.search(text):
                contact_matched = True
                break
                
        if contact_matched:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Parent or user contact detail pattern detected.")
            findings.append("contact_detail_found")
            high_risk_flags.append("contact_detail_found")
        else:
            checks_passed.append("no_parent_contact")
            
        # 10. Payload size check
        max_bytes = config.get("max_payload_bytes") or 65536
        import json
        payload_bytes = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else b""
        if len(payload_bytes) > max_bytes:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Payload size ({len(payload_bytes)} bytes) exceeds limit.")
            findings.append("payload_size_exceeded")
        else:
            checks_passed.append("payload_size_ok")
            
        # 11. Source device ID check
        if not source_device_id or not source_device_id.strip():
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Missing source_device_id.")
            findings.append("missing_source_device_id")
        else:
            checks_passed.append("source_device_id_present")
            
        # 12. Target agent allowlist check
        allowed_agents = config.get("allowed_target_agents") or ["hermes", "openclaw", "auto"]
        if target_agent not in allowed_agents:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Unapproved target agent '{target_agent}'.")
            findings.append("target_agent_unapproved")
        else:
            checks_passed.append("target_agent_allowlisted")
            
        # 13. Endpoint domain allowlist check
        allowed_domains = config.get("allowed_endpoint_domains") or ["supabase.co"]
        domain_matched = False
        try:
            parsed = urllib.parse.urlparse(endpoint_url)
            netloc = parsed.netloc or parsed.path
            domain = netloc.split(":")[0]
            for allowed in allowed_domains:
                if domain == allowed or domain.endswith("." + allowed):
                    domain_matched = True
                    break
        except Exception as e:
            log_audit_event("POLICY_BLOCKED", "policy_gate", f"Invalid endpoint URL schema: {e}")
            
        if not domain_matched:
            log_audit_event("POLICY_BLOCKED", "policy_gate", "Endpoint domain is not allowlisted.")
            findings.append("endpoint_domain_unapproved")
        else:
            checks_passed.append("endpoint_domain_allowlisted")
            
        # Determine overall risk level
        if high_risk_flags:
            risk_level = "high"
        elif findings:
            risk_level = "medium"
        else:
            risk_level = "low"
            
        safe_auto = (not findings and len(checks_passed) == 14)
        
        if safe_auto:
            log_audit_event("POLICY_APPROVED", "policy_gate", "External dispatch payload passed all Policy Gate requirements.")
            
        return OutboundAssessment(
            automatic_classification=sensitivity,
            risk_level=risk_level,
            findings=findings,
            checks_passed=checks_passed,
            suggested_redactions=suggested_redactions,
            safe_auto_allowed=safe_auto,
        )

    def assess_v2_item(
        self,
        item_kind: str,
        target_agent: str,
        content: Dict[str, Any],
        task: Optional[Dict[str, Any]] = None,
        vault_path: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> OutboundAssessment:
        """Evaluates all v2 payload fields across privacy and safety policy rules."""
        config = config or {}
        checks_passed: List[str] = []
        findings: List[str] = []
        suggested_redactions: List[str] = []
        high_risk_flags: List[str] = []

        if item_kind not in ("record_only", "agent_task"):
            findings.append("invalid_item_kind")
            high_risk_flags.append("invalid_item_kind")
        else:
            checks_passed.append("valid_item_kind")

        # Collect text by field for field-level attribution
        field_texts: Dict[str, str] = {}
        if isinstance(content, dict):
            field_texts["content.title"] = str(content.get("title") or "")
            field_texts["content.summary"] = str(content.get("summary") or "")
            if content.get("transcript"):
                field_texts["content.transcript"] = str(content.get("transcript"))

            tags = content.get("tags")
            if isinstance(tags, list):
                field_texts["content.tags"] = " ".join([str(t) for t in tags])

            s_fields = content.get("structured_fields") or content.get("category_fields") or {}
            if isinstance(s_fields, dict):
                field_texts["content.structured_fields"] = " ".join(
                    [f"{k}:{v}" for k, v in s_fields.items()]
                )

        if item_kind == "agent_task" and isinstance(task, dict):
            field_texts["task.title"] = str(task.get("title") or "")
            field_texts["task.instructions"] = str(task.get("instructions") or "")

        # 1. Student Registry scanning across all fields
        registry_loaded = False
        from pathlib import Path

        if vault_path and Path(vault_path).exists():
            try:
                registry = StudentRegistry(vault_path)
                if (
                    hasattr(registry, "data")
                    and isinstance(registry.data, dict)
                    and "students" in registry.data
                ):
                    registry_loaded = True
            except Exception as e:
                log_audit_event("POLICY_BLOCKED", "policy_gate", f"Failed to load student registry: {e}")

        if registry_loaded:
            checks_passed.append("student_registry_loaded")
            students = registry.data.get("students", {})
            student_names = []
            for key, entry in students.items():
                if isinstance(entry, dict) and "display_name" in entry:
                    student_names.append(entry["display_name"])
                else:
                    student_names.append(key)

            name_matched = False
            for student_name in student_names:
                name_clean = student_name.strip()
                if not name_clean or len(name_clean) < 2:
                    continue
                escaped_name = re.escape(name_clean.lower())
                flexible = escaped_name.replace(r"\ ", r"\s+").replace(" ", r"\s+")
                pattern = re.compile(r"(?<![A-Za-z])" + flexible + r"(?![A-Za-z])", re.IGNORECASE)

                for field_name, text in field_texts.items():
                    if pattern.search(text):
                        name_matched = True
                        findings.append(f"{field_name}: student_name_match ('{name_clean}')")
                        suggested_redactions.append(f"Remove student name '{name_clean}' from {field_name}")

            if name_matched:
                high_risk_flags.append("student_name_match")
            else:
                checks_passed.append("no_student_registry_match")
        else:
            checks_passed.append("student_registry_skipped")

        # 2. Contact details (email & phone)
        email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
        phone_pattern = re.compile(r"\b\d{8,15}\b")
        contact_matched = False

        for field_name, text in field_texts.items():
            if email_pattern.search(text):
                contact_matched = True
                findings.append(f"{field_name}: email_address")
                suggested_redactions.append(f"Redact email address from {field_name}")
            if phone_pattern.search(text):
                contact_matched = True
                findings.append(f"{field_name}: phone_number")
                suggested_redactions.append(f"Redact phone number from {field_name}")

        if contact_matched:
            high_risk_flags.append("contact_detail_found")
        else:
            checks_passed.append("no_contact_details")

        # 3. Medical & Safeguarding / Forbidden Terms
        forbidden_terms = [
            "welfare", "medical", "absence", "behaviour", "behavior", "pickup", "custody",
            "iep", "suspension", "incident", "counselling", "counseling", "psychologist",
            "injury", "illness", "allergic", "allergy", "medication", "cps", "safety plan"
        ]
        forbidden_matched = False
        for term in forbidden_terms:
            pattern = re.compile(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", re.IGNORECASE)
            for field_name, text in field_texts.items():
                if pattern.search(text):
                    forbidden_matched = True
                    findings.append(f"{field_name}: forbidden_term ('{term}')")
                    suggested_redactions.append(f"Remove sensitive term '{term}' from {field_name}")

        if forbidden_matched:
            high_risk_flags.append("forbidden_term_matched")
        else:
            checks_passed.append("no_forbidden_terms")

        # 4. Local File Paths
        path_patterns = [
            r"[A-Za-z]:\\[^\s\n]+", r"[A-Za-z]:/[^\s\n]+",
            r"/Users/[^\s\n]+", r"/home/[^\s\n]+",
            r"\\Users\\[^\s\n]+", r"\.obsidian"
        ]
        path_matched = False
        for pat_str in path_patterns:
            pattern = re.compile(pat_str, re.IGNORECASE)
            for field_name, text in field_texts.items():
                if pattern.search(text):
                    path_matched = True
                    findings.append(f"{field_name}: local_file_path")
                    suggested_redactions.append(f"Remove local path from {field_name}")

        if path_matched:
            high_risk_flags.append("local_path_found")
        else:
            checks_passed.append("no_local_file_paths")

        # 5. Audio Extensions
        audio_extensions = [r"\.wav\b", r"\.mp3\b", r"\.m4a\b", r"\.aac\b", r"\.flac\b", r"\.ogg\b"]
        audio_matched = False
        for ext in audio_extensions:
            pattern = re.compile(ext, re.IGNORECASE)
            for field_name, text in field_texts.items():
                if pattern.search(text):
                    audio_matched = True
                    findings.append(f"{field_name}: audio_extension_found")

        if audio_matched:
            high_risk_flags.append("audio_extension_found")
        else:
            checks_passed.append("no_audio_attached")

        # 6. Credentials / Secret Patterns
        secret_patterns = [
            r"sk-[a-zA-Z0-9_\-]{20,}",
            r"bearer\s+[a-zA-Z0-9._\-]{20,}",
            r"ghp_[a-zA-Z0-9]{20,}",
        ]
        secret_matched = False
        for sec_pat in secret_patterns:
            pattern = re.compile(sec_pat, re.IGNORECASE)
            for field_name, text in field_texts.items():
                if pattern.search(text):
                    secret_matched = True
                    findings.append(f"{field_name}: credential_secret_found")

        if secret_matched:
            high_risk_flags.append("credential_secret_found")
        else:
            checks_passed.append("no_credentials_found")

        # Target agent validation — hermes is not a registered v2 adapter
        # Only 'openclaw' is supported until a real Hermes adapter is implemented.
        allowed_agents = config.get("allowed_target_agents") or ["openclaw"]
        if target_agent not in allowed_agents:
            findings.append(f"target_agent_unapproved: '{target_agent}'")
            high_risk_flags.append("target_agent_unapproved")
        else:
            checks_passed.append("target_agent_allowlisted")

        # Determine overall risk
        if high_risk_flags:
            risk_level = "high"
        elif findings:
            risk_level = "medium"
        else:
            risk_level = "low"

        safe_auto = (risk_level == "low" and not findings)

        return OutboundAssessment(
            automatic_classification="non_sensitive" if risk_level == "low" else "sensitive",
            risk_level=risk_level,
            findings=findings,
            checks_passed=checks_passed,
            suggested_redactions=suggested_redactions,
            safe_auto_allowed=safe_auto,
        )

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
        assessment = self.assess_outbound(
            category=category,
            sensitivity=sensitivity,
            safe_task=safe_task,
            transcript=transcript,
            payload=payload,
            source_device_id=source_device_id,
            target_agent=target_agent,
            endpoint_url=endpoint_url,
            vault_path=vault_path,
            config=config,
        )
        return assessment.safe_auto_allowed, assessment.checks_passed

