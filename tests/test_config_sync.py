"""Tests for config_sync.perform_config_sync."""

from pathlib import Path
from unittest.mock import patch

import pytest

from devctl.core import config_sync
from devctl.core.config_sync import (
    _config_sync_interval_seconds,
    perform_config_sync,
)


@pytest.fixture
def sync_tmp_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config_sync, "_LAST_SYNC_FILE", tmp_path / ".last_config_sync")


def test_config_sync_interval_minutes_override_hours() -> None:
    s = _config_sync_interval_seconds(
        {
            "DEVCTL_CONFIG_SYNC_INTERVAL_MINUTES": "30",
            "DEVCTL_CONFIG_SYNC_INTERVAL_HOURS": "999",
        }
    )
    assert s == 30 * 60


def test_config_sync_interval_hours_when_minutes_unset() -> None:
    assert _config_sync_interval_seconds({"DEVCTL_CONFIG_SYNC_INTERVAL_HOURS": "2"}) == 2 * 3600


def test_config_sync_interval_fractional_minutes() -> None:
    assert _config_sync_interval_seconds({"DEVCTL_CONFIG_SYNC_INTERVAL_MINUTES": "0.5"}) == 30.0


def test_perform_config_sync_no_repos(sync_tmp_paths: None) -> None:
    with patch("devctl.core.config_sync.list_repos", return_value={}):
        assert perform_config_sync(force=True, notify=False) == []


def test_perform_config_sync_rate_limited(sync_tmp_paths: None) -> None:
    with (
        patch("devctl.core.config_sync.list_repos", return_value={"s": {"url": "u", "path": "/x"}}),
        patch("devctl.core.config_sync._is_sync_due", return_value=False),
    ):
        assert perform_config_sync(force=False, notify=False) == []


def test_perform_config_sync_pulls_and_notifies(sync_tmp_paths: None, tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    with (
        patch(
            "devctl.core.config_sync.list_repos",
            return_value={
                "my-slug": {
                    "url": "https://git.example/repo.git",
                    "path": str(repo),
                    "branch": "feature-x",
                }
            },
        ),
        patch("devctl.core.config_sync.fetch_and_has_updates", return_value=True),
        patch("devctl.core.config_sync.clone_or_pull") as pull,
        patch(
            "devctl.core.config_sync.apply_protocols",
            return_value=("v1", [], [], []),
        ),
        patch("devctl.core.config_sync.register_repo") as reg,
        patch("devctl.utils.notify.send_notification") as notify,
    ):
        pull.side_effect = lambda url, branch=None: repo
        out = perform_config_sync(force=True, notify=True)
        assert out == ["my-slug"]
        pull.assert_called_once_with("https://git.example/repo.git", branch="feature-x")
        reg.assert_called_once()
        assert reg.call_args.kwargs.get("branch") == "feature-x"
        notify.assert_called_once()


def test_perform_config_sync_skip_missing_path(sync_tmp_paths: None) -> None:
    with (
        patch(
            "devctl.core.config_sync.list_repos",
            return_value={"x": {"url": "u", "path": str(Path("/nonexistent-path-xyz"))}},
        ),
        patch("devctl.core.config_sync.fetch_and_has_updates") as fetch,
        patch("devctl.utils.notify.send_notification") as notify,
    ):
        assert perform_config_sync(force=True, notify=False) == []
        fetch.assert_not_called()
        notify.assert_not_called()


def test_perform_config_sync_skip_no_updates(sync_tmp_paths: None, tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    with (
        patch(
            "devctl.core.config_sync.list_repos",
            return_value={"s": {"url": "u", "path": str(repo)}},
        ),
        patch("devctl.core.config_sync.fetch_and_has_updates", return_value=False),
        patch("devctl.core.config_sync.clone_or_pull") as pull,
        patch("devctl.utils.notify.send_notification") as notify,
    ):
        assert perform_config_sync(force=True, notify=False) == []
        pull.assert_not_called()
        notify.assert_not_called()


def test_perform_config_sync_notify_false(sync_tmp_paths: None, tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    with (
        patch(
            "devctl.core.config_sync.list_repos",
            return_value={"s": {"url": "u", "path": str(repo)}},
        ),
        patch("devctl.core.config_sync.fetch_and_has_updates", return_value=True),
        patch("devctl.core.config_sync.clone_or_pull", return_value=repo),
        patch("devctl.core.config_sync.apply_protocols", return_value=("v1", [], [], [])),
        patch("devctl.core.config_sync.register_repo"),
        patch("devctl.utils.notify.send_notification") as notify,
    ):
        assert perform_config_sync(force=True, notify=False) == ["s"]
        notify.assert_not_called()
