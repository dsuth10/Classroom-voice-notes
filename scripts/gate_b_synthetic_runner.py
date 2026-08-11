#!/usr/bin/env python3
"""Produce honest Step 13 pre-flight and Gate B staging evidence.

Local checks provide regression coverage only.  They are deliberately not
reported as completed Gate B scenarios: Gate B requires a separate Supabase
staging project and several operational rehearsals.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).parent.parent
REPORT_DIR = ROOT_DIR / "reports"
LOCAL_API_URL = "http://127.0.0.1:54321"


@dataclass(frozen=True)
class LocalCheck:
    scenario_id: int
    name: str
    node_id: str
    note: str


# These are deliberately narrow, named regression checks.  Passing them is
# local pre-flight coverage, not proof that the full Gate B scenario ran.
LOCAL_CHECKS = (
    LocalCheck(1, "sharing_off_creates_no_local_outbound_state", "tests/unit/test_outbound_integration_pr12.py::test_pr12_sharing_off_creates_no_outbound_state", "Local-only coverage."),
    LocalCheck(2, "review_all_record_only_exports_csv", "tests/integration/test_outbound_sharing_e2e_pr10.py::test_full_outbound_sharing_e2e_flow", "Uses local stores and synthetic content."),
    LocalCheck(3, "openclaw_fake_gateway_acceptance", "tests/integration/test_openclaw_adapter_fake_gateway.py::TestOpenClawAdapterFakeGateway::test_fake_gateway_success", "Uses the controlled local fake gateway."),
    LocalCheck(4, "preview_approval_hash_identity", "tests/unit/test_outbound_review_dialog.py::test_dialog_save_edits_and_approve", "Does not prove a remote hash match."),
    LocalCheck(5, "rejection_keeps_item_unapproved", "tests/unit/test_outbound_review_dialog.py::test_dialog_approve_and_reject", "Does not make a remote request."),
    LocalCheck(6, "edited_content_recalculates_hash", "tests/unit/test_outbound_review_store.py::test_update_draft_updates_columns_and_recalculates_hash", "Local reassessment/storage coverage."),
    LocalCheck(7, "high_risk_trusted_mode_pauses", "tests/unit/test_outbound_integration_pr12.py::test_pr12_trusted_high_risk_pauses_for_review", "Does not prove server-side entitlement rejection."),
    LocalCheck(8, "trusted_low_risk_creates_authorised_release", "tests/unit/test_outbound_routing_service.py::test_routing_mode_trusted_auto_low_risk", "Exercises the local trusted-release decision; it does not prove a staging entitlement or remote completion."),
    LocalCheck(9, "wrong_policy_or_high_risk_pauses", "tests/unit/test_outbound_assessment_pr5.py::test_trusted_mode_pauses_on_v2_high_risk", "Local policy coverage."),
    LocalCheck(10, "pending_submission_recovery", "tests/unit/test_external_agent_dispatcher.py::test_retry_pending_generates_fresh_request_nonces_per_attempt", "Does not simulate a deployed Edge response."),
    LocalCheck(11, "exact_outbox_retry_is_idempotent", "tests/unit/test_worker_edge_lifecycle.py::test_outbox_submission_retry_idempotency", "Local durable-outbox coverage."),
    LocalCheck(12, "unknown_openclaw_outcome_is_quarantined", "tests/unit/test_outbound_worker_v2_step9.py::test_openclaw_unknown_outcome_quarantine_prevents_reexecution", "Worker restart/reclaim coverage remains a staging requirement."),
    LocalCheck(13, "post_commit_retry_avoids_duplicate_record", "tests/unit/test_record_concurrency_failure.py::test_crash_after_commit_returns_idempotent_success", "Record consumer only."),
    LocalCheck(14, "insufficient_or_mismatched_lease_is_rejected", "tests/unit/test_outbound_worker_v2_step9.py::test_lease_margin_expired_fails_claim", "Does not prove a second real worker claim."),
    LocalCheck(15, "local_edge_signature_and_nonce_replay_rejection", "tests/integration/test_local_v2_edge_auth.py::test_local_v2_edge_rejects_replayed_request_nonce", "Real local Edge Function authentication coverage."),
    LocalCheck(16, "local_edge_rejects_oversized_and_deeply_nested_content", "tests/integration/test_local_v2_edge_auth.py::test_local_v2_edge_rejects_oversized_and_deeply_nested_payloads", "Real local Edge Function payload-boundary coverage."),
)


def git_state() -> tuple[str, bool]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT_DIR, capture_output=True, text=True, check=True).stdout.strip())
    return sha, not dirty


def local_preflight_environment() -> dict[str, str]:
    """Load only ignored local test settings, without logging their values."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.setdefault("CVN_BROKER_ENV", "staging")

    dotenv_path = ROOT_DIR / "supabase" / "functions" / ".env"
    if dotenv_path.exists():
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip())
    command = ["npx.cmd" if os.name == "nt" else "npx", "supabase", "status", "-o", "env"]
    result = subprocess.run(command, cwd=ROOT_DIR, capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"')
    env["SUPABASE_URL"] = env["API_URL"]
    env["SUPABASE_SERVICE_ROLE_KEY"] = env["SERVICE_ROLE_KEY"]
    env["SUPABASE_ANON_KEY"] = env["ANON_KEY"]
    env["CVN_TEST_BASE_URL"] = env["FUNCTIONS_URL"]
    env["AGENT_BROKER_BEARER_TOKEN"] = env.get("CVN_WORKER_BEARER_TOKEN", "")
    env["AGENT_BROKER_HMAC_SECRET"] = env.get("CVN_WORKER_HMAC_SECRET", "")
    return env


def validate_local_target(env: dict[str, str]) -> str:
    """Ensure the runner cannot accidentally use a remote Supabase project."""
    url = env.get("SUPABASE_URL", LOCAL_API_URL).rstrip("/")
    if url != LOCAL_API_URL:
        raise ValueError(f"Local pre-flight requires SUPABASE_URL={LOCAL_API_URL}")
    return url


def run_node(node_id: str, env: dict[str, str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="cvn-gate-b-") as directory:
        junit_path = Path(directory) / "result.xml"
        command = [sys.executable, "-m", "pytest", node_id, "-p", "no:cacheprovider", f"--junitxml={junit_path}"]
        process = subprocess.run(command, cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=90)
        if not junit_path.exists():
            return {"status": "FAILED", "summary": "Pytest produced no structured result", "returncode": process.returncode}
        suite = ET.parse(junit_path).getroot()
        cases = suite.findall(".//testcase")
        if len(cases) != 1:
            return {"status": "FAILED", "summary": f"Expected one test case, got {len(cases)}", "returncode": process.returncode}
        case = cases[0]
        if case.find("skipped") is not None:
            return {"status": "SKIPPED", "summary": "Required test was skipped", "returncode": process.returncode}
        if case.find("failure") is not None or case.find("error") is not None or process.returncode:
            return {"status": "FAILED", "summary": "Required test failed", "returncode": process.returncode}
        return {"status": "PASSED", "summary": "Exact regression test passed", "returncode": process.returncode}


def write_report(target: str, sha: str, clean: bool, results: list[dict[str, Any]], validation_error: str | None) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    suffix = now.strftime("%Y%m%d_%H%M%S")
    metadata = {
        "timestamp": now.isoformat(),
        "commit_sha": sha,
        "worktree_clean": clean,
        "target": target,
        "scope": "Step 13 local pre-flight" if target == "local" else "Formal Gate B staging",
        "gate_b_complete": False,
        "validation_error": validation_error,
    }
    evidence = {"metadata": metadata, "local_regression_checks": results, "remaining_gate_b_requirements": [
        "Dedicated staging proof is required for all 20 Gate B scenarios.",
        "Scenarios 17–20 require recorded operational rehearsals: monitoring, retention/restore, emergency disable, credential rotation and rollback.",
        "Gate C governance approval is separate from Gate B.",
    ]}
    json_path = REPORT_DIR / f"gate_b_evidence_{suffix}.json"
    json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    passed = sum(item["status"] == "PASSED" for item in results)
    lines = [
        "# Outbound Sharing Verification Report",
        "",
        f"- Scope: {metadata['scope']}",
        f"- Commit: `{sha}`",
        f"- Worktree clean: {'yes' if clean else 'no'}",
        f"- Local regression checks: {passed}/{len(results)} passed",
        "- Gate B completion: **not established by this report**",
    ]
    if validation_error:
        lines.extend(["", f"Validation error: {validation_error}"])
    lines.extend(["", "| Scenario | Local regression check | Status | Note |", "|---|---|---|---|"])
    for item in results:
        lines.append(f"| {item['scenario_id']} | `{item['name']}` | {item['status']} | {item['note']} |")
    lines.extend(["", "## Remaining requirements", "", "- Run the scenarios against the separate approved staging project.", "- Attach operator evidence for scenarios 17–20.", "- Complete Gate C governance outside this runner."])
    markdown_path = REPORT_DIR / f"gate_b_report_{suffix}.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run honest outbound-sharing pre-flight evidence checks")
    parser.add_argument("--env", choices=("local", "staging"), default="local")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    sha, clean = git_state()
    if args.env == "staging" and args.allow_dirty:
        print("--allow-dirty is permitted only for local pre-flight; staging evidence requires a clean worktree.")
        return 1
    if not clean and not args.allow_dirty:
        print("Refusing release evidence from a dirty worktree. Use --allow-dirty only for local pre-flight.")
        return 1

    validation_error = None
    if args.env == "staging":
        validation_error = (
            "Formal Gate B staging is not implemented by this local runner. "
            "Use docs/gate-b-staging-evidence.md and the dedicated staging harness."
        )
        env: dict[str, str] = {}
    else:
        env = local_preflight_environment()
        try:
            validate_local_target(env)
        except ValueError as error:
            validation_error = str(error)

    results: list[dict[str, Any]] = []
    if validation_error is None:
        for check in LOCAL_CHECKS:
            outcome = run_node(check.node_id, env)
            results.append({"scenario_id": check.scenario_id, "name": check.name, "node_id": check.node_id, "note": check.note, **outcome})
    json_path, markdown_path = write_report(args.env, sha, clean, results, validation_error)
    print(f"Evidence: {json_path}")
    print(f"Report: {markdown_path}")
    if validation_error or any(item["status"] != "PASSED" for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
