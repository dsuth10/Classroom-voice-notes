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
