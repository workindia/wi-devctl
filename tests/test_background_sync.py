"""Tests for background_sync install helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devctl.core.background_sync import install_background_sync, uninstall_background_sync


def test_install_background_sync_darwin_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    logs = tmp_path / ".devctl" / "logs"
    monkeypatch.setattr(
        "devctl.core.background_sync.get_logs_dir",
        lambda: logs,
    )
    monkeypatch.setattr(
        "devctl.core.background_sync.get_background_sync_log_path",
        lambda: logs / "background-sync.log",
    )
    fake_devctl = str(tmp_path / "devctl")
    Path(fake_devctl).write_text("#!/bin/sh\necho ok\n")

    with (
        patch("devctl.core.background_sync.platform.system", return_value="darwin"),
        patch("devctl.core.background_sync._get_devctl_path", return_value=fake_devctl),
        patch("devctl.core.background_sync.subprocess.run") as run,
    ):
        run.return_value = MagicMock(returncode=0)

        ok, msg = install_background_sync()
    assert ok is True
    assert "launchd" in msg.lower()
    assert "background-sync.log" in msg
    plist = tmp_path / "Library" / "LaunchAgents" / "com.devctl.config-sync.plist"
    assert plist.exists()
    plist_text = plist.read_text()
    assert fake_devctl in plist_text
    assert "PYTHONUNBUFFERED" in plist_text
    assert (logs / "background-sync.log").exists()


def test_install_background_sync_no_binary() -> None:
    with (
        patch("devctl.core.background_sync.platform.system", return_value="linux"),
        patch("devctl.core.background_sync._get_devctl_path", return_value=None),
    ):
        ok, msg = install_background_sync()
    assert ok is False
    assert "Could not find" in msg


def test_uninstall_background_sync_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("devctl.core.background_sync.Path.home", lambda: tmp_path)
    with patch("devctl.core.background_sync.platform.system", return_value="darwin"):
        ok, msg = uninstall_background_sync()
    assert ok is True
    assert "not installed" in msg.lower()
