# app/config/environment.py
import os
from typing import Optional

def get_broker_env() -> str:
    """Returns the validated broker environment, or raises RuntimeError if invalid/missing.
    
    Accepts only 'staging' or 'production'.
    """
    env = os.getenv("CVN_BROKER_ENV", "").strip().lower()
    if env not in ("staging", "production"):
        raise RuntimeError(f"CVN_BROKER_ENV must be exactly 'staging' or 'production'. Got: '{env}'")
    return env

def get_env_credential_ref(base_ref: str) -> str:
    """Produces explicit, predictable environment-specific secret names for keyring store lookup.
    
    Accepts:
        'key_id', 'bearer_token', 'hmac_secret'
    Returns:
        The exact keyring reference name (e.g. cvn_broker_bearer_token_staging)
    """
    env = get_broker_env()
    if base_ref == "key_id":
        return f"cvn_broker_key_id_{env}"
    elif base_ref == "bearer_token":
        return f"cvn_broker_bearer_token_{env}"
    elif base_ref == "hmac_secret":
        return f"cvn_broker_hmac_secret_{env}"
    else:
        raise RuntimeError(f"Unknown credential base reference: {base_ref}")
