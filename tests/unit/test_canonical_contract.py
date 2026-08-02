"""Unit tests verifying canonical JSON sorting and SHA-256 hash against shared cross-platform vectors.

Both Python (this file) and TypeScript (outbound_contract.ts) must produce byte-for-byte identical
canonical JSON strings and SHA-256 hashes for every vector in tests/fixtures/canonical_vectors.json.
"""

import hashlib
import json
from pathlib import Path
import pytest

from app.destinations.outbound_review_store import compute_content_hash


def load_vectors() -> list[dict]:
    fixture_path = Path(__file__).parent.parent / "fixtures" / "canonical_vectors.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return data["vectors"]


@pytest.mark.parametrize("vector", load_vectors(), ids=[v["name"] for v in load_vectors()])
def test_canonical_json_matches_fixture(vector: dict) -> None:
    """Canonical JSON string must exactly match the expected_canonical_json in the fixture."""
    obj = {
        "item_kind": vector["item_kind"],
        "target_agent": vector["target_agent"] or "",
        "content": vector["content"],
        "task": vector["task"] or {},
    }
    canonical_str = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert canonical_str == vector["expected_canonical_json"], (
        f"Vector '{vector['name']}' canonical JSON mismatch:\n  Got: {canonical_str}\n  Exp: {vector['expected_canonical_json']}"
    )


@pytest.mark.parametrize("vector", load_vectors(), ids=[v["name"] for v in load_vectors()])
def test_sha256_hash_matches_fixture(vector: dict) -> None:
    """SHA-256 hash of canonical JSON must exactly match the expected_hash in the fixture."""
    computed = compute_content_hash(
        vector["item_kind"],
        vector["target_agent"],
        vector["content"],
        vector["task"],
    )
    assert computed == vector["expected_hash"], (
        f"Vector '{vector['name']}' hash mismatch:\n  Got: {computed}\n  Exp: {vector['expected_hash']}"
    )
