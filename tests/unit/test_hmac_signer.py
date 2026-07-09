from app.destinations.hmac_signer import sign, verify

def test_sign_and_verify() -> None:
    secret = "my_super_secret_key"
    body = b'{"task_id":"CVN-123","title":"Clean"}'
    
    # Sign
    signature = sign(body, secret)
    assert isinstance(signature, str)
    assert len(signature) == 64  # Hex-encoded SHA256 is 64 characters
    
    # Verify correct signature
    assert verify(body, secret, signature) is True
    
    # Case insensitivity check
    assert verify(body, secret, signature.upper()) is True
    
    # Verify incorrect signature
    assert verify(body, secret, "wrong_signature") is False
    
    # Verify tampered body
    assert verify(body + b" ", secret, signature) is False
    
    # Verify incorrect secret
    assert verify(body, "wrong_secret", signature) is False
