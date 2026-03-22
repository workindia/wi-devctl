"""Tests for updater."""

from unittest.mock import patch

import pytest

from devctl.core.updater import (
    _get_platform_key,
    _fetch_manifest,
    check_for_update,
)


def test_get_platform_key() -> None:
    """Platform key format."""
    key = _get_platform_key()
    assert "-" in key
    assert key in ("darwin-amd64", "darwin-arm64", "linux-amd64", "linux-arm64", "windows-amd64")


def test_check_for_update_with_manifest() -> None:
    """Check for update with custom manifest."""
    manifest = {
        "latest_version": "v99.0.0",
        "downloads": {
            "darwin-arm64": "https://example.com/devctl",
            "darwin-amd64": "https://example.com/devctl",
            "linux-amd64": "https://example.com/devctl",
            "windows-amd64": "https://example.com/devctl.exe",
        },
    }
    with patch("devctl.core.updater._fetch_manifest", return_value=manifest):
        has_update, version, url = check_for_update("https://example.com/manifest.json")
        assert has_update is True
        assert version == "v99.0.0"
        assert url is not None


def test_check_for_update_no_newer() -> None:
    """No update when already current."""
    manifest = {
        "latest_version": "v0.1.0",
        "downloads": {
            "darwin-arm64": "https://example.com/devctl",
        },
    }
    with patch("devctl.core.updater._fetch_manifest", return_value=manifest):
        has_update, version, url = check_for_update("https://example.com/manifest.json")
        assert has_update is False


def test_check_for_update_no_platform() -> None:
    """No update when platform not in manifest."""
    manifest = {
        "latest_version": "v99.0.0",
        "downloads": {
            "linux-amd64": "https://example.com/devctl",
        },
    }
    with patch("devctl.core.updater._fetch_manifest", return_value=manifest):
        with patch("devctl.core.updater._get_platform_key", return_value="darwin-arm64"):
            has_update, version, url = check_for_update("https://example.com/manifest.json")
            assert has_update is False
            assert url is None
