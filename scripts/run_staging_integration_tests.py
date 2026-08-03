"""
scripts/run_staging_integration_tests.py
Pulls staging secrets from Windows Credential Manager and runs the two
integration test suites that require environment variables:

  - tests/integration/test_supabase_broker_milestone_2.py
    (Scenario 8 = nonce replay protection via deployed Edge Functions)
  - tests/integration/test_migration_019_nonce_rpc_integration.py
    (direct PostgREST RPC calls — requires SUPABASE_URL + SERVICE_ROLE_KEY)

Usage:
    .\.venv\Scripts\python.exe scripts/run_staging_integration_tests.py [--replay-only] [--migration-only]

For Migration 019 tests you must first set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
either as environment variables or via keyring (supabase_url, supabase_service_role_key).
"""
import os
import sys
import subprocess
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config.keyring_store import get_secret  # noqa: E402


def load_env() -> dict[str, str]:
    env = dict(os.environ)

    mapping = {
        "CVN_BEARER_TOKEN":           ["staging_cvn_bearer_token", "cvn_bearer_token"],
        "CVN_HMAC_SECRET":            ["staging_cvn_hmac_secret",  "cvn_hmac_secret"],
        "AGENT_BROKER_BEARER_TOKEN":  ["agent_broker_bearer_token"],
        "AGENT_BROKER_HMAC_SECRET":   ["agent_broker_hmac_secret"],
        "SUPABASE_URL":               ["supabase_url"],
        "SUPABASE_SERVICE_ROLE_KEY":  ["supabase_service_role_key", "service_role_key"],
        "SUPABASE_ANON_KEY":          ["supabase_anon_key"],
    }

    for env_var, keyring_names in mapping.items():
        if not env.get(env_var):
            for name in keyring_names:
                val = get_secret(name)
                if val:
                    env[env_var] = val
                    print(f"[+] Loaded {env_var} from keyring key '{name}'")
                    break
            else:
                print(f"[-] {env_var} not found in environment or keyring — tests requiring it will skip")

    return env


def run(args: list[str], env: dict[str, str]) -> int:
    result = subprocess.run(args, env=env)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Run staging integration tests with keyring credentials")
    parser.add_argument("--replay-only", action="store_true", help="Run only the Milestone 2 replay test")
    parser.add_argument("--migration-only", action="store_true", help="Run only the Migration 019 RPC test")
    parser.add_argument("-v", "--verbose", action="store_true")
    opts = parser.parse_args()

    env = load_env()
    pytest_bin = os.path.join(os.path.dirname(sys.executable), "pytest.exe")
    base_cmd = [pytest_bin, "-v" if opts.verbose else "-q", "-p", "no:cacheprovider"]

    exit_codes: list[int] = []

    if not opts.migration_only:
        print("\n" + "="*60)
        print("RUNNING: Milestone 2 Staging Tests (includes Scenario 8 — nonce replay via Edge Functions)")
        print("="*60)
        code = run(base_cmd + ["tests/integration/test_supabase_broker_milestone_2.py"], env)
        exit_codes.append(code)

    if not opts.replay_only:
        print("\n" + "="*60)
        print("RUNNING: Migration 019 PostgreSQL RPC Integration Tests")
        print("="*60)
        code = run(base_cmd + ["tests/integration/test_migration_019_nonce_rpc_integration.py"], env)
        exit_codes.append(code)

    sys.exit(max(exit_codes, default=0))


if __name__ == "__main__":
    main()
