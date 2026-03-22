"""Tests for repo_manager."""

import pytest

from devctl.core.repo_manager import url_to_slug


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
