"""Unit tests for RFC 8785 Canonical JSON scheme and cross-language test vectors."""

import json
from pathlib import Path
import pytest

from app.destinations.canonical_json import (
    build_canonical_object,
    canonicalize_json,
    compute_canonical_content_hash,
)


def test_canonical_vectors_fixture() -> None:
    """Verifies that Python canonicalization matches expected JSON strings and SHA-256 hashes in canonical_vectors.json."""
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "canonical_vectors.json"
    assert fixture_path.exists(), f"Fixture missing at {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_data = json.load(f)

    vectors = fixture_data.get("vectors", [])
    assert len(vectors) > 0, "No vectors found in canonical_vectors.json"

    for vec in vectors:
        name = vec["name"]
        item_kind = vec["item_kind"]
        target_agent = vec["target_agent"]
        content = vec["content"]
        task = vec.get("task")

        expected_json = vec["expected_canonical_json"]
        expected_hash = vec["expected_hash"]

        canonical_str, digest = compute_canonical_content_hash(
            item_kind=item_kind,
            target_agent=target_agent,
            content=content,
            task=task,
        )

        assert canonical_str == expected_json, f"[{name}] JSON mismatch:\nGot:  {canonical_str}\nWant: {expected_json}"
        assert digest == expected_hash, f"[{name}] Hash mismatch:\nGot:  {digest}\nWant: {expected_hash}"


def test_canonicalize_json_key_sorting_and_whitespace() -> None:
    """Tests that object key sorting and zero whitespace are strictly enforced."""
    raw = {"z": 1, "a": {"c": 3, "b": 2}}
    res = canonicalize_json(raw)
    assert res == '{"a":{"b":2,"c":3},"z":1}'


def test_canonicalize_json_float_integer_normalization() -> None:
    """Tests that whole floats (1.0) normalize to integer (1) to match JavaScript stringify."""
    raw = {"count": 1.0, "val": 2.5}
    res = canonicalize_json(raw)
    assert res == '{"count":1,"val":2.5}'
