"""Unit and structural validation tests for PR 6 & PR 7 Supabase Edge Function validation."""

from pathlib import Path
import pytest


def test_edge_function_exists_and_uses_v2_schema() -> None:
    edge_file = Path("supabase/functions/cvn-submit-outbound-item/index.ts")
    assert edge_file.exists(), "Edge function cvn-submit-outbound-item/index.ts missing"
    content = edge_file.read_text(encoding="utf-8")

    assert 'const SCHEMA_VERSION = "cvn.outbound_item.v2";' in content
    assert "idempotency_key must be a non-empty string" in content
    assert "nonce must be a non-empty string" in content
    assert "isValidHexSha256(p?.content_hash)" in content


def test_edge_function_validates_approval_content_hash_match() -> None:
    edge_file = Path("supabase/functions/cvn-submit-outbound-item/index.ts")
    content = edge_file.read_text(encoding="utf-8")

    assert "privacy.approval block required for human_approval/trusted_mode" in content
    assert "privacy.checks_passed array required for automatic_policy" in content
    assert "content_hash_mismatch" in content
    assert "approved_content_hash_mismatch" in content


def test_edge_function_canonicalization_and_limits() -> None:
    edge_file = Path("supabase/functions/cvn-submit-outbound-item/index.ts")
    content = edge_file.read_text(encoding="utf-8")

    assert 'client_auth.ts' in content
    assert "MAX_BODY_SIZE_BYTES = 512 * 1024" in content
    assert "body_too_large" in content
    assert "status: 413" in content


def test_edge_function_security_and_rpc_structure() -> None:
    edge_file = Path("supabase/functions/cvn-submit-outbound-item/index.ts")
    content = edge_file.read_text(encoding="utf-8")
    auth_file = Path("supabase/functions/_shared/client_auth.ts")
    auth_content = auth_file.read_text(encoding="utf-8")

    assert "authenticateClient" in content
    assert "x-cvn-signature" in auth_content
    assert "hmacSha256Hex" in auth_content
    assert "MAX_TIMESTAMP_AGE_SECONDS" in auth_content
    assert 'supabase.rpc("cvn_submit_outbound_item"' in content
    assert "duplicate_idempotency_key" in content
    assert "status: 409" in content

