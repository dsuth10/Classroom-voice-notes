from app.audit.audit_logger import log_audit_event

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
