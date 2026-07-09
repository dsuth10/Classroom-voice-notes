import keyring
from typing import Optional
from app.audit.audit_logger import log_audit_event

SERVICE_NAME = "ClassroomVoiceNotes"

def get_secret(ref_name: str) -> Optional[str]:
    """Retrieves a secret from the OS credential store (Windows Credential Manager)."""
    try:
        val = keyring.get_password(SERVICE_NAME, ref_name)
        if val is not None:
            return val
        return None
    except Exception as e:
        log_audit_event("KEYRING_READ_ERROR", "system", f"Failed to read secret '{ref_name}' from keyring: {e}")
        return None

def set_secret(ref_name: str, value: str) -> bool:
    """Sets a secret in the OS credential store."""
    try:
        keyring.set_password(SERVICE_NAME, ref_name, value)
        log_audit_event("KEYRING_WRITE_SUCCESS", "system", f"Successfully stored secret '{ref_name}' in keyring")
        return True
    except Exception as e:
        log_audit_event("KEYRING_WRITE_ERROR", "system", f"Failed to write secret '{ref_name}' to keyring: {e}")
        return False

def delete_secret(ref_name: str) -> bool:
    """Deletes a secret from the OS credential store."""
    try:
        keyring.delete_password(SERVICE_NAME, ref_name)
        log_audit_event("KEYRING_DELETE_SUCCESS", "system", f"Successfully deleted secret '{ref_name}' from keyring")
        return True
    except keyring.errors.PasswordDeleteError:
        return False
    except Exception as e:
        log_audit_event("KEYRING_DELETE_ERROR", "system", f"Failed to delete secret '{ref_name}' from keyring: {e}")
        return False

def has_secret(ref_name: str) -> bool:
    """Checks if a secret exists in the OS credential store without retrieving it."""
    try:
        val = keyring.get_password(SERVICE_NAME, ref_name)
        return val is not None
    except Exception:
        return False
