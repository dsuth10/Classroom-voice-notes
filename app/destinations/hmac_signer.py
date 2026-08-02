import hmac
import hashlib

def sign(raw_json_body: bytes, hmac_secret: str) -> str:
    """Computes HMAC-SHA256 hex signature over raw JSON bytes."""
    secret_bytes = hmac_secret.encode("utf-8")
    signature = hmac.new(secret_bytes, raw_json_body, hashlib.sha256)
    return signature.hexdigest()

def verify(raw_json_body: bytes, hmac_secret: str, expected_signature: str) -> bool:
    """Performs a timing-safe verification of the signature."""
    actual_signature = sign(raw_json_body, hmac_secret)
    return hmac.compare_digest(actual_signature.lower(), expected_signature.lower())


def create_client_request_headers(
    method: str,
    endpoint_url: str,
    raw_body_str: str,
    bearer_token: str,
    hmac_secret: str,
    client_key_id: str = "default_client_key",
    nonce: str | None = None,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Generates standard 5-element client request headers with HMAC signature over METHOD|PATH|TIMESTAMP|NONCE|BODY."""
    import time
    import uuid
    from urllib.parse import urlparse

    parsed = urlparse(endpoint_url)
    path = parsed.path or "/functions/v1/cvn-submit-outbound-item"
    ts = timestamp or str(int(time.time()))
    n = nonce or uuid.uuid4().hex

    canonical = f"{method.upper()}|{path}|{ts}|{n}|{raw_body_str}"
    sig = sign(canonical.encode("utf-8"), hmac_secret)

    return {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "X-CVN-Client-Key-Id": client_key_id,
        "X-CVN-Signature": sig,
        "X-CVN-Timestamp": ts,
        "X-CVN-Nonce": n,
    }
