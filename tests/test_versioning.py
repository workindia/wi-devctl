"""Tests for versioning / state."""

import json
from pathlib import Path

import pytest

from devctl.core import versioning
from devctl.core.versioning import (
    get_repo_version,
    list_repos,
    load_state,
    register_repo,
)


@pytest.fixture
def isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect state.json into tmp_path."""
    state_path = tmp_path / "state.json"

    def _state() -> Path:
        return state_path

    monkeypatch.setattr(versioning, "get_state_path", _state)
    return state_path


def test_get_repo_version_from_version_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    assert get_repo_version(tmp_path) == "1.2.3"


def test_get_repo_version_from_protocol(tmp_path: Path) -> None:
    (tmp_path / "protocol.yaml").write_text("version: v9\nprotocols: []\n")
    assert get_repo_version(tmp_path) == "v9"


def test_get_repo_version_unknown(tmp_path: Path) -> None:
    (tmp_path / "protocol.yaml").write_text("protocols: []\n")
    assert get_repo_version(tmp_path) == "unknown"


def test_register_and_list_repos(isolated_state: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    register_repo("org-kit", "https://example.com/org-kit.git", repo, "v1")
    repos = list_repos()
    assert "org-kit" in repos
    assert repos["org-kit"]["url"].endswith("org-kit.git")
    assert repos["org-kit"]["path"] == str(repo)
    assert repos["org-kit"]["version"] == "v1"
    data = json.loads(isolated_state.read_text())
    assert "org-kit" in data["repos"]


def test_load_state_missing_file(isolated_state: Path) -> None:
    assert not isolated_state.exists()
    s = load_state()
    assert s.get("repos") == {}
