"""Tests for updater."""

import os
import sys
from unittest.mock import patch

import pytest

from devctl.core.updater import (
    _get_platform_key,
    _fetch_manifest,
    check_for_update,
    perform_update,
)


def test_get_platform_key() -> None:
    """Platform key format: os-arch."""
    key = _get_platform_key()
    parts = key.split("-", 1)
    assert len(parts) == 2
    assert parts[0] and parts[1]


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


def test_perform_update_force_no_download_url() -> None:
    """update-cli when manifest has no asset for platform exits without download."""
    with patch("devctl.core.updater.check_for_update", return_value=(False, "v1.0.0", None)):
        has_update, ver, url = perform_update(None, force=True)
        assert has_update is False
        assert url is None


def test_perform_update_skips_when_not_due() -> None:
    """Background check returns immediately when rate-limited."""
    with patch("devctl.core.updater._is_update_check_due", return_value=False):
        has_update, ver, url = perform_update(None, force=False)
        assert has_update is False
        assert url is None


def test_perform_update_resets_pyinstaller_environment(monkeypatch, tmp_path) -> None:
    """Restart the replaced binary as a new PyInstaller process."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    monkeypatch.setattr(
        "devctl.core.updater.check_for_update",
        lambda manifest_url: (True, "v9.9.9", "https://example.com/devctl"),
    )

    class _Response:
        def read(self) -> bytes:
            return b"new-binary"

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args) -> bool:
            return False

    monkeypatch.setattr("devctl.core.updater.open_url", lambda *args, **kwargs: _Response())

    installed = tmp_path / "devctl"
    installed.write_bytes(b"old-binary")
    monkeypatch.setattr(sys, "executable", str(installed))

    seen = {}

    def _execv(exe: str, argv: list) -> None:
        seen["exe"] = exe
        seen["argv"] = argv
        seen["reset"] = os.environ.get("PYINSTALLER_RESET_ENVIRONMENT")

    monkeypatch.setattr("devctl.core.updater.os.execv", _execv)

    perform_update(None, force=True)

    assert seen["reset"] == "1"
    assert seen["exe"] == str(installed)
    assert seen["argv"][0] == str(installed)
    assert installed.read_bytes() == b"new-binary"


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
