# app/config/environment.py
import os
from urllib.parse import urlparse

BROKER_PROJECT_REFS = {
    "staging": "ukqkkgzimhtjhlnmlyao",
    "production": "slvzyasosjiteimonzen",
}

def get_broker_env() -> str:
    """Returns the validated broker environment, or raises RuntimeError if invalid/missing.
    
    Accepts only 'staging' or 'production'.
    """
    env = os.getenv("CVN_BROKER_ENV", "")
    if env not in ("staging", "production"):
        raise RuntimeError(f"CVN_BROKER_ENV must be exactly 'staging' or 'production'. Got: '{env}'")
    return env

def validate_broker_endpoint(endpoint_url: str) -> None:
    """Require an HTTPS Supabase function URL for the active broker environment."""
    env = get_broker_env()
    expected_host = f"{BROKER_PROJECT_REFS[env]}.supabase.co"

    try:
        parsed = urlparse(endpoint_url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Broker endpoint URL is malformed") from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/functions/v1/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            f"Broker endpoint must target the approved {env} Supabase functions host"
        )

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
