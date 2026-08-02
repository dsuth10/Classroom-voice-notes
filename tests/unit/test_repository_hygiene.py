from pathlib import Path

from scripts.check_repository_hygiene import (
    extract_local_markdown_targets,
    find_broken_markdown_links,
    find_forbidden_tracked_paths,
    find_missing_ignore_rules,
)


def test_forbidden_tracked_paths_detects_private_and_generated_files() -> None:
    paths = [
        ".env",
        ".env.production",
        ".env.template",
        "app/__pycache__/module.cpython-311.pyc",
        "notes/recording.wav",
        "scratch/probe.py",
        "supabase/.temp/project-ref",
        "app/controller.py",
    ]

    assert find_forbidden_tracked_paths(paths) == [
        ".env",
        ".env.production",
        "app/__pycache__/module.cpython-311.pyc",
        "notes/recording.wav",
        "scratch/probe.py",
        "supabase/.temp/project-ref",
    ]


def test_ignore_rule_check_reports_only_missing_rules(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(
        "\n".join(
            [
                ".env",
                ".venv/",
                "__pycache__/",
                ".codex-test-temp/",
                "*.pyc",
                "*.wav",
                "scratch/",
            ]
        ),
        encoding="utf-8",
    )

    assert find_missing_ignore_rules(tmp_path) == ["supabase/.temp/"]


def test_markdown_target_extraction_ignores_urls_and_anchors() -> None:
    markdown = """
    [local](docs/guide.md)
    [angle target](<docs/a file.md>)
    [with title](docs/runbook.md "Runbook")
    [web](https://example.com)
    [section](#usage)
    """

    assert extract_local_markdown_targets(markdown) == [
        "docs/guide.md",
        "docs/a file.md",
        "docs/runbook.md",
    ]


def test_broken_link_check_reports_missing_maintained_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "[exists](LICENSE)\n[missing](docs/missing.md)\n[web](https://example.com)\n",
        encoding="utf-8",
    )
    (tmp_path / "LICENSE").write_text("test", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.check_repository_hygiene.MAINTAINED_MARKDOWN",
        ("README.md",),
    )

    assert find_broken_markdown_links(tmp_path) == ["README.md -> docs/missing.md"]
