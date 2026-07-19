"""Tests for repo_manager."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devctl.core.repo_manager import (
    clone_or_pull,
    fetch_and_has_updates,
    resolve_default_branch,
    url_to_slug,
)


def test_url_to_slug_github() -> None:
    """Convert GitHub URL to slug (HTTP and SSH)."""
    assert url_to_slug("https://github.com/org/repo") == "org-repo"
    assert url_to_slug("https://github.com/org/repo.git") == "org-repo"
    assert url_to_slug("git@github.com:org/repo.git") == "org-repo"
    assert url_to_slug("git@github.com:org/repo") == "org-repo"


def test_url_to_slug_with_path() -> None:
    """Handle path with slashes."""
    assert url_to_slug("https://git.example.com/foo/bar/baz") == "foo-bar-baz"


def test_url_to_slug_sanitize() -> None:
    """Sanitize special chars."""
    slug = url_to_slug("https://github.com/my-org/my_repo")
    assert slug == "my-org-my_repo"


def _mock_run_sequence(outputs: list[tuple[int, str]]) -> MagicMock:
    """subprocess.run returns successive CompletedProcess-like results."""
    calls = {"i": 0}

    def fake_run(*_a, **_k):
        idx = calls["i"]
        calls["i"] += 1
        rc, out = outputs[idx]
        m = MagicMock()
        m.returncode = rc
        m.stdout = out
        return m

    return MagicMock(side_effect=fake_run)


def test_fetch_and_has_updates_true_when_behind(tmp_path: Path) -> None:
    """git reports commits on origin/main not in HEAD."""
    repo = tmp_path / "g"
    repo.mkdir()
    run = _mock_run_sequence(
        [
            (0, ""),  # git fetch
            (0, "main\n"),  # rev-parse HEAD branch
            (0, "2\n"),  # rev-list count behind
        ]
    )
    with patch("devctl.core.repo_manager.subprocess.run", run):
        assert fetch_and_has_updates(repo) is True


def test_fetch_and_has_updates_false_when_even(tmp_path: Path) -> None:
    run = _mock_run_sequence(
        [
            (0, ""),
            (0, "main\n"),
            (0, "0\n"),
        ]
    )
    with patch("devctl.core.repo_manager.subprocess.run", run):
        assert fetch_and_has_updates(tmp_path) is False


def test_fetch_and_has_updates_false_on_fetch_failure(tmp_path: Path) -> None:
    run = MagicMock(side_effect=subprocess.CalledProcessError(1, "git"))
    with patch("devctl.core.repo_manager.subprocess.run", run):
        assert fetch_and_has_updates(tmp_path) is False


def test_resolve_default_branch() -> None:
    proc = MagicMock()
    proc.stdout = "ref: refs/heads/main\tHEAD\n"
    with patch("devctl.core.repo_manager.subprocess.run", return_value=proc):
        assert resolve_default_branch("https://github.com/org/repo.git") == "main"


def test_clone_or_pull_with_branch_new_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repos_dir = tmp_path / "repos"
    monkeypatch.setattr("devctl.core.repo_manager.get_repos_dir", lambda: repos_dir)
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("devctl.core.repo_manager.subprocess.run", side_effect=fake_run):
        path = clone_or_pull("https://github.com/org/repo.git", branch="feature-x")

    assert path == repos_dir / "org-repo"
    assert ["git", "clone", "--branch", "feature-x", "https://github.com/org/repo.git", str(path)] in [
        c for c in calls
    ]


def test_clone_or_pull_with_branch_existing_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repos_dir = tmp_path / "repos"
    repo_path = repos_dir / "org-repo"
    repo_path.mkdir(parents=True)
    monkeypatch.setattr("devctl.core.repo_manager.get_repos_dir", lambda: repos_dir)
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("devctl.core.repo_manager.subprocess.run", side_effect=fake_run):
        path = clone_or_pull("https://github.com/org/repo.git", branch="feature-x")

    assert path == repo_path
    assert ["git", "fetch", "origin"] in calls
    assert ["git", "checkout", "feature-x"] in calls
    assert ["git", "pull", "--ff-only"] in calls
