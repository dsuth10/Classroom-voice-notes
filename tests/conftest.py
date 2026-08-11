"""Shared test isolation for application-owned local storage."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_app_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep settings and audit writes out of a developer's AppData directory."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local_app_data"))
