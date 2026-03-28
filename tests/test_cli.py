"""CLI integration tests (Click)."""

import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from devctl.cli.main import cli


def _env(tmp_home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(tmp_home),
        "DEVCTL_SKIP_AUTO_UPDATE": "1",
    }


def test_cli_version(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["--version"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "devctl" in r.output.lower() or "0.1" in r.output


def test_cli_list_no_repos(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["list"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "No managed repos" in r.output


def test_cli_list_with_repos(tmp_path: Path) -> None:
    devctl_home = tmp_path / ".devctl"
    devctl_home.mkdir()
    state = {
        "repos": {
            "org-kit": {
                "url": "https://github.com/org/kit",
                "path": str(tmp_path / "r"),
                "version": "v1",
            }
        }
    }
    (devctl_home / "state.json").write_text(json.dumps(state))
    runner = CliRunner()
    r = runner.invoke(cli, ["list"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "org-kit" in r.output
    assert "org/kit" in r.output


def test_cli_ai_kit_sync_no_repos(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["ai-kit", "sync"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "No managed repos" in r.output


def test_cli_ai_kit_sync_up_to_date(tmp_path: Path) -> None:
    devctl_home = tmp_path / ".devctl"
    devctl_home.mkdir()
    (devctl_home / "state.json").write_text(
        json.dumps({"repos": {"x": {"url": "u", "path": str(tmp_path)}}})
    )
    with patch("devctl.core.config_sync.perform_config_sync", return_value=[]):
        runner = CliRunner()
        r = runner.invoke(cli, ["ai-kit", "sync"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "all repos up to date" in r.output.lower()


def test_cli_ai_kit_sync_updated(tmp_path: Path) -> None:
    devctl_home = tmp_path / ".devctl"
    devctl_home.mkdir()
    (devctl_home / "state.json").write_text(
        json.dumps({"repos": {"x": {"url": "u", "path": str(tmp_path)}}})
    )
    with patch("devctl.core.config_sync.perform_config_sync", return_value=["a", "b"]):
        runner = CliRunner()
        r = runner.invoke(cli, ["ai-kit", "sync"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "Synced: a" in r.output
    assert "Synced: b" in r.output


def test_cli_ai_kit_sync_background_logs_summary(tmp_path: Path) -> None:
    devctl_home = tmp_path / ".devctl"
    devctl_home.mkdir()
    (devctl_home / "state.json").write_text(
        json.dumps({"repos": {"x": {"url": "u", "path": str(tmp_path)}}})
    )
    with patch("devctl.core.config_sync.perform_config_sync", return_value=[]):
        runner = CliRunner()
        r = runner.invoke(cli, ["ai-kit", "sync", "--background"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "devctl ai-kit sync:" in r.output
    assert "up to date" in r.output
    assert re.search(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]", r.output)


def test_cli_ai_kit_sync_background_no_repos(tmp_path: Path) -> None:
    with patch("devctl.core.config_sync.perform_config_sync", return_value=[]):
        runner = CliRunner()
        r = runner.invoke(cli, ["ai-kit", "sync", "--background"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "no managed repos" in r.output


def test_cli_update_cli_no_op(tmp_path: Path) -> None:
    with patch("devctl.core.updater.perform_update", return_value=(False, "0.1.0", None)):
        runner = CliRunner()
        r = runner.invoke(cli, ["update-cli"], env=_env(tmp_path))
    assert r.exit_code == 0
    assert "Already up to date" in r.output


def test_cli_devspace_help(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["devspace", "--help"], env=_env(tmp_path))
    assert r.exit_code == 0


def test_cli_local_help(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["local", "--help"], env=_env(tmp_path))
    assert r.exit_code == 0
