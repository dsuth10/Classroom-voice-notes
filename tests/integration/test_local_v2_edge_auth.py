"""Local Edge Runtime authentication smoke coverage for outbound v2."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import pytest
import requests


BASE_URL = os.environ.get("CVN_TEST_BASE_URL", "").rstrip("/")
BEARER_TOKEN = os.environ.get("CVN_BEARER_TOKEN", "")
HMAC_SECRET = os.environ.get("CVN_HMAC_SECRET", "")
MISSING_ENV = not BASE_URL or not BEARER_TOKEN or not HMAC_SECRET


def _headers(body: str, nonce: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    path = "/cvn-submit-outbound-item"
    canonical = f"POST|{path}|{timestamp}|{nonce}|{body}"
    signature = hmac.new(
        HMAC_SECRET.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
        "X-CVN-Client-Key-Id": "local-preflight-client",
        "X-CVN-Timestamp": timestamp,
        "X-CVN-Nonce": nonce,
        "X-CVN-Signature": signature,
    }


@pytest.mark.skipif(MISSING_ENV, reason="Missing local Edge test credentials")
def test_local_v2_edge_rejects_replayed_request_nonce() -> None:
    """A validly authenticated malformed request consumes its nonce exactly once."""
    body = "{}"
    nonce = secrets.token_hex(16)
    first = requests.post(
        f"{BASE_URL}/cvn-submit-outbound-item",
        data=body,
        headers=_headers(body, nonce),
        timeout=15,
    )
    assert first.status_code == 400, first.text
    assert first.json()["error"] == "schema_validation_failed"

    replay = requests.post(
        f"{BASE_URL}/cvn-submit-outbound-item",
        data=body,
        headers=_headers(body, nonce),
        timeout=15,
    )
    assert replay.status_code == 401, replay.text
    assert replay.json()["error"] == "unauthorized"
