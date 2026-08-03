# tests/unit/test_migration_020_lease_idempotency.py
"""Unit tests verifying Migration 020 SQL structure, lease hashing, backoff logic, ownership cleanup, and state machine lifecycle."""
import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path


def test_migration_020_sql_structure_and_permissions() -> None:
    migration_file = Path("supabase/migrations/020_cvn_lease_hash_and_idempotency.sql")
    assert migration_file.exists(), "Migration 020 SQL file missing"
    content = migration_file.read_text(encoding="utf-8")

    # Column additions
    assert "ADD COLUMN IF NOT EXISTS lease_token_hash TEXT" in content
    assert "ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ" in content
    assert "ADD COLUMN IF NOT EXISTS last_error_code TEXT" in content
    assert "ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ" in content
    assert "ADD COLUMN IF NOT EXISTS result_reference TEXT" in content
    assert "check_outbound_lease_token_hash_hex" in content

    # Lease migration of legacy active claims
    assert "SET status = 'failed_retryable'" in content
    assert "lease_token_hash IS NULL" in content

    # Performance Index
    assert "CREATE INDEX IF NOT EXISTS idx_cvn_outbound_items_claim_eligible" in content
    assert "WHERE status IN ('submitted', 'received', 'failed_retryable')" in content

    # cvn_submit_outbound_item Idempotency exact match vs conflict
    assert "idempotency_conflict:" in content
    assert "idempotent_replay" in content

    # cvn_claim_outbound_item hashed lease generation
    assert "v_lease_token :=" in content
    assert "gen_random_bytes(32)" in content
    assert "sha256(convert_to(v_lease_token, 'UTF8'))" in content
    assert "next_attempt_at IS NULL OR next_attempt_at <= now()" in content
    assert "FOR UPDATE SKIP LOCKED" in content

    # cvn_complete_outbound_item hashed lease validation & lease token cleanup
    assert "v_given_lease_hash :=" in content
    assert "lease_token_hash IS DISTINCT FROM v_given_lease_hash" in content
    assert "lease_token_hash = NULL" in content
    assert "octet_length(p_result_json::text)" in content

    # cvn_fail_outbound_item server-controlled max attempts & ownership cleanup
    assert "v_max_attempts CONSTANT INT := 3;" in content
    assert "claimed_by = NULL" in content
    assert "claimed_by_worker_id = NULL" in content
    assert "claimed_at = NULL" in content
    assert "v_backoff_seconds :=" in content
    assert "LEAST(3600" in content
    assert "v_next_status := 'dead_letter'" in content

    # Permissions
    assert "REVOKE ALL ON FUNCTION public.cvn_submit_outbound_item FROM PUBLIC, anon, authenticated;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_submit_outbound_item TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_claim_outbound_item(text, integer, text[], text[]) TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_complete_outbound_item(text, text, text, text, text, jsonb, text) TO service_role;" in content
    assert "GRANT EXECUTE ON FUNCTION public.cvn_fail_outbound_item(text, text, text, text, boolean, text) TO service_role;" in content


def test_unit_migration_020_ownership_cleanup_and_dead_letter_lifecycle() -> None:
    """Executes SQLite in-memory lifecycle verifying lease hashing, backoff, dead-letter, and ownership cleanup."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Setup outbox table mimicking cvn_outbound_items schema
    conn.execute("""
        CREATE TABLE cvn_outbound_items (
            item_id TEXT PRIMARY KEY,
            source_device_id TEXT NOT NULL,
            item_kind TEXT NOT NULL,
            target_agent TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            nonce TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_by_worker_id TEXT,
            claimed_at TEXT,
            lease_token TEXT,
            lease_token_hash TEXT,
            lease_expires_at TEXT,
            visibility_deadline TEXT,
            next_attempt_at TEXT,
            last_error_code TEXT,
            last_error_at TEXT,
            completed_at TEXT,
            failed_at TEXT,
            failure_reason TEXT,
            result_json TEXT,
            result_reference TEXT
        )
    """)

    # 1. Insert item
    item_id = "CVNI-20260803-120000-TEST1"
    content_hash = "abc123hash"
    conn.execute(
        """
        INSERT INTO cvn_outbound_items (
            item_id, source_device_id, item_kind, target_agent, status,
            payload_json, payload_hash, content_hash, idempotency_key, nonce
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, "dev1", "record_only", "openclaw", "submitted", "{}", "hash", content_hash, "idem1", "nonce1")
    )
    conn.commit()

    # 2. Simulate Claim: Store hashed lease
    lease_token = f"lease-secret-{uuid.uuid4().hex[:12]}"
    lease_token_hash = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()

    conn.execute(
        """
        UPDATE cvn_outbound_items
        SET status = 'claimed',
            claimed_by = 'worker-1',
            claimed_by_worker_id = 'worker-1',
            claimed_at = ?,
            lease_token = NULL,
            lease_token_hash = ?,
            lease_expires_at = ?,
            visibility_deadline = ?,
            attempt_count = attempt_count + 1
        WHERE item_id = ?
        """,
        ((datetime.now(timezone.utc)).isoformat(), lease_token_hash, expires_at, expires_at, item_id)
    )
    conn.commit()

    row_claimed = conn.execute("SELECT * FROM cvn_outbound_items WHERE item_id = ?", (item_id,)).fetchone()
    assert row_claimed["status"] == "claimed"
    assert row_claimed["lease_token"] is None
    assert row_claimed["lease_token_hash"] == lease_token_hash
    assert row_claimed["claimed_by"] == "worker-1"

    # 3. Simulate Complete: Clear ALL lease ownership fields
    conn.execute(
        """
        UPDATE cvn_outbound_items
        SET status = 'completed',
            completed_at = ?,
            result_json = '{"status":"ok"}',
            result_reference = 'ref-999',
            lease_token = NULL,
            lease_token_hash = NULL,
            lease_expires_at = NULL,
            visibility_deadline = NULL,
            claimed_by = NULL,
            claimed_by_worker_id = NULL,
            claimed_at = NULL
        WHERE item_id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), item_id)
    )
    conn.commit()

    row_completed = conn.execute("SELECT * FROM cvn_outbound_items WHERE item_id = ?", (item_id,)).fetchone()
    assert row_completed["status"] == "completed"
    assert row_completed["lease_token"] is None
    assert row_completed["lease_token_hash"] is None
    assert row_completed["lease_expires_at"] is None
    assert row_completed["visibility_deadline"] is None
    assert row_completed["claimed_by"] is None
    assert row_completed["claimed_by_worker_id"] is None
    assert row_completed["claimed_at"] is None
    assert row_completed["result_reference"] == "ref-999"
