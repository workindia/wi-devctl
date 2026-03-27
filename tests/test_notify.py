"""Tests for OS notifications helper."""

from unittest.mock import patch

import pytest

from devctl.utils.notify import send_notification


def test_send_notification_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVCTL_SKIP_NOTIFY", "1")
    with patch("devctl.utils.notify.subprocess.run") as run:
        send_notification("t", "body")
        run.assert_not_called()


def test_send_notification_darwin_calls_osascript(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVCTL_SKIP_NOTIFY", raising=False)
    with (
        patch("devctl.utils.notify.sys.platform", "darwin"),
        patch("devctl.utils.notify.subprocess.run") as run,
    ):
        send_notification("devctl", "hello")
        run.assert_called_once()
        args = run.call_args[0][0]
        assert args[0] == "osascript"
