"""Fail when repository safety and documentation invariants are not met."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

REQUIRED_FILES = (
    ".env.template",
    ".github/workflows/ci.yml",
    "LICENSE",
    "README.md",
    "deploy/README.md",
    "docs/architecture/003-cvn-worker-contract.md",
    "docs/operations/environment-and-credentials.md",
    "docs/operations/outbox-recovery.md",
    "docs/phase-2e-delivery-plan.md",
    "pyproject.toml",
    "uv.lock",
)

REQUIRED_IGNORE_RULES = (
    ".env",
    ".venv/",
    "__pycache__/",
    ".codex-test-temp/",
    "*.pyc",
    "*.wav",
    "scratch/",
    "supabase/.temp/",
)

MAINTAINED_MARKDOWN = (
    "README.md",
    "deploy/README.md",
    "docs/architecture/003-cvn-worker-contract.md",
    "docs/operations/environment-and-credentials.md",
    "docs/operations/outbox-recovery.md",
    "docs/phase-2e-delivery-plan.md",
)

README_MARKERS = (
    "Python: 3.11+",
    "**Production:** Not authorised",
    "uv run pytest tests",
    "docs/operations/environment-and-credentials.md",
    "docs/operations/outbox-recovery.md",
)

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
EXTERNAL_TARGET = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


def find_missing_required_files(root: Path) -> list[str]:
    """Return required paths that do not exist."""
    return [path for path in REQUIRED_FILES if not (root / path).exists()]


def find_missing_ignore_rules(root: Path) -> list[str]:
    """Return safety rules absent from the root .gitignore."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return list(REQUIRED_IGNORE_RULES)

    rules = {
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return [rule for rule in REQUIRED_IGNORE_RULES if rule not in rules]


def find_forbidden_tracked_paths(paths: list[str]) -> list[str]:
    """Return generated, private, or ephemeral paths that Git must not track."""
    forbidden: list[str] = []

    for raw_path in paths:
        path = PurePosixPath(raw_path.replace("\\", "/"))
        parts = tuple(part.casefold() for part in path.parts)
        name = path.name.casefold()
        suffix = path.suffix.casefold()

        is_private_environment = name.startswith(".env") and name != ".env.template"
        is_ephemeral_directory = (
            parts[:1] == ("scratch",)
            or parts[:2] == ("supabase", ".temp")
            or "__pycache__" in parts
        )
        is_generated_file = (
            suffix in {".pyc", ".pyo", ".wav"}
            or name in {"audit.log", "external_outbox.db", "settings.json"}
        )

        if is_private_environment or is_ephemeral_directory or is_generated_file:
            forbidden.append(path.as_posix())

    return sorted(set(forbidden))


def extract_local_markdown_targets(markdown: str) -> list[str]:
    """Extract local path targets from inline Markdown links and images."""
    targets: list[str] = []

    for match in MARKDOWN_LINK.finditer(markdown):
        target = match.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        else:
            target = target.split(maxsplit=1)[0]

        target = unquote(target)
        if not target or target.startswith("#") or EXTERNAL_TARGET.match(target):
            continue

        targets.append(target.split("#", maxsplit=1)[0])

    return targets


def find_broken_markdown_links(root: Path) -> list[str]:
    """Return broken local links in maintained project documentation."""
    broken: list[str] = []

    for relative_document in MAINTAINED_MARKDOWN:
        document = root / relative_document
        if not document.is_file():
            continue

        markdown = document.read_text(encoding="utf-8")
        for target in extract_local_markdown_targets(markdown):
            if target.startswith("/"):
                destination = root / target.lstrip("/")
            else:
                destination = document.parent / target

            if not destination.exists():
                broken.append(f"{relative_document} -> {target}")

    return sorted(set(broken))


def find_missing_readme_markers(root: Path) -> list[str]:
    """Return operational statements that must remain visible in the README."""
    readme = root / "README.md"
    if not readme.is_file():
        return list(README_MARKERS)

    content = readme.read_text(encoding="utf-8")
    return [marker for marker in README_MARKERS if marker not in content]


def tracked_paths(root: Path) -> list[str]:
    """Read the repository's tracked paths from Git."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def check_repository(root: Path) -> list[str]:
    """Run all repository hygiene checks and return human-readable failures."""
    failures: list[str] = []

    failures.extend(
        f"required file is missing: {path}" for path in find_missing_required_files(root)
    )
    failures.extend(
        f".gitignore is missing safety rule: {rule}" for rule in find_missing_ignore_rules(root)
    )
    failures.extend(
        f"forbidden generated or private path is tracked: {path}"
        for path in find_forbidden_tracked_paths(tracked_paths(root))
    )
    failures.extend(
        f"maintained documentation has a broken local link: {link}"
        for link in find_broken_markdown_links(root)
    )
    failures.extend(
        f"README is missing operational marker: {marker}"
        for marker in find_missing_readme_markers(root)
    )

    return failures


def main() -> int:
    """Run checks from the repository root and report a CI-friendly result."""
    root = Path(__file__).resolve().parent.parent

    try:
        failures = check_repository(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Repository hygiene check could not run: {exc}", file=sys.stderr)
        return 2

    if failures:
        print("Repository hygiene check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
