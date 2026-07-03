"""Tests for claude_hooks protocol."""

import json
from pathlib import Path

import pytest

from devctl.core.claude_hooks import sync_claude_hooks
from devctl.core.protocol_engine import Protocol, execute_protocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(tmp_path: Path, hooks_yaml: str | None = None, scripts: dict[str, str] | None = None) -> Path:
    source = tmp_path / "hooks"
    source.mkdir()
    if hooks_yaml is not None:
        (source / "hooks.yaml").write_text(hooks_yaml)
    for name, content in (scripts or {}).items():
        (source / name).write_text(content)
    return source


def _read_settings(path: Path) -> dict:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# sync_claude_hooks — hooks.yaml present
# ---------------------------------------------------------------------------

def test_hooks_written_into_settings(tmp_path: Path) -> None:
    """hooks from hooks.yaml are written into settings.json."""
    source = _make_source(tmp_path, hooks_yaml="""
hooks:
  PreToolUse:
    - matcher: Skill
      hooks:
        - type: command
          command: "python3 ~/.devctl/hooks/tracker.py"
""")
    settings = tmp_path / "settings.json"
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    data = _read_settings(settings)
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]
    assert data["hooks"]["PreToolUse"][0]["matcher"] == "Skill"


def test_hooks_preserves_other_settings(tmp_path: Path) -> None:
    """Existing non-hooks settings are preserved after sync."""
    source = _make_source(tmp_path, hooks_yaml="hooks:\n  PreToolUse: []")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "claude-opus", "theme": "dark"}))
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    data = _read_settings(settings)
    assert data["model"] == "claude-opus"
    assert data["theme"] == "dark"
    assert "hooks" in data


def test_hooks_replaces_previous_hooks(tmp_path: Path) -> None:
    """An updated hooks.yaml fully replaces the previous hooks section."""
    source = _make_source(tmp_path, hooks_yaml="hooks:\n  PostToolUse: []")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"old": True}]}}))
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    data = _read_settings(settings)
    assert "PostToolUse" in data["hooks"]
    assert "PreToolUse" not in data["hooks"]


# ---------------------------------------------------------------------------
# sync_claude_hooks — hooks.yaml absent or empty hooks key
# ---------------------------------------------------------------------------

def test_no_hooks_yaml_removes_hooks_key(tmp_path: Path) -> None:
    """Absent hooks.yaml removes 'hooks' from existing settings (clean uninstall)."""
    source = _make_source(tmp_path)  # no hooks.yaml
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": []}, "other": True}))
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    data = _read_settings(settings)
    assert "hooks" not in data
    assert data["other"] is True


def test_empty_hooks_key_removes_hooks(tmp_path: Path) -> None:
    """hooks.yaml with no 'hooks' key removes the hooks section from settings."""
    source = _make_source(tmp_path, hooks_yaml="# no hooks defined")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": []}}))
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    data = _read_settings(settings)
    assert "hooks" not in data


def test_no_existing_settings_file(tmp_path: Path) -> None:
    """Works when settings.json does not exist yet — creates it."""
    source = _make_source(tmp_path, hooks_yaml="hooks:\n  PreToolUse: []")
    settings = tmp_path / "settings.json"
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    assert settings.exists()
    data = _read_settings(settings)
    assert "hooks" in data


def test_corrupt_settings_treated_as_empty(tmp_path: Path) -> None:
    """Corrupt settings.json is treated as empty — hooks written cleanly."""
    source = _make_source(tmp_path, hooks_yaml="hooks:\n  PreToolUse: []")
    settings = tmp_path / "settings.json"
    settings.write_text("not valid json {{")
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    data = _read_settings(settings)
    assert "hooks" in data


# ---------------------------------------------------------------------------
# sync_claude_hooks — script copying
# ---------------------------------------------------------------------------

def test_scripts_copied_to_dest(tmp_path: Path) -> None:
    """Non-yaml files in source are copied to scripts_dest."""
    source = _make_source(
        tmp_path,
        hooks_yaml="hooks: {}",
        scripts={"tracker.py": "print('tracking')", "helper.sh": "#!/bin/sh"},
    )
    settings = tmp_path / "settings.json"
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    assert (scripts_dest / "tracker.py").exists()
    assert (scripts_dest / "tracker.py").read_text() == "print('tracking')"
    assert (scripts_dest / "helper.sh").exists()
    assert not (scripts_dest / "hooks.yaml").exists()  # hooks.yaml not copied


def test_hooks_yaml_not_copied_to_scripts(tmp_path: Path) -> None:
    """hooks.yaml itself is never copied into scripts_dest."""
    source = _make_source(tmp_path, hooks_yaml="hooks: {}")
    settings = tmp_path / "settings.json"
    scripts_dest = tmp_path / "scripts"

    sync_claude_hooks(source, settings, scripts_dest=scripts_dest)

    assert not (scripts_dest / "hooks.yaml").exists()


# ---------------------------------------------------------------------------
# protocol_engine integration
# ---------------------------------------------------------------------------

def test_execute_protocol_claude_hooks(tmp_path: Path) -> None:
    """execute_protocol dispatches claude_hooks and returns empty lists."""
    source = tmp_path / "hooks"
    source.mkdir()
    (source / "hooks.yaml").write_text("hooks:\n  PreToolUse: []")

    settings = tmp_path / "settings.json"
    scripts_dest = tmp_path / "scripts"

    protocol = Protocol(
        name="test-hooks",
        type="claude_hooks",
        source="hooks",
        target=str(settings),
        obligations=[],
        recommendations=[],
    )

    # Patch scripts_dest by monkeypatching get_devctl_home inside claude_hooks
    import devctl.core.claude_hooks as ch
    original = ch.get_devctl_home
    ch.get_devctl_home = lambda: scripts_dest
    try:
        missing_obl, missing_rec = execute_protocol(protocol, tmp_path, "slug", do_backup=False)
    finally:
        ch.get_devctl_home = original

    assert missing_obl == []
    assert missing_rec == []
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert "hooks" in data


def test_execute_protocol_claude_hooks_obligations_ignored(tmp_path: Path) -> None:
    """Obligations/recommendations are not checked for claude_hooks (target is a file)."""
    source = tmp_path / "hooks"
    source.mkdir()
    (source / "hooks.yaml").write_text("hooks: {}")

    settings = tmp_path / "settings.json"
    scripts_dest = tmp_path / "scripts"

    protocol = Protocol(
        name="test-hooks",
        type="claude_hooks",
        source="hooks",
        target=str(settings),
        obligations=["some/path.json"],  # would fail if target-dir checked
        recommendations=["other/path.md"],
    )

    import devctl.core.claude_hooks as ch
    original = ch.get_devctl_home
    ch.get_devctl_home = lambda: scripts_dest
    try:
        missing_obl, missing_rec = execute_protocol(protocol, tmp_path, "slug", do_backup=False)
    finally:
        ch.get_devctl_home = original

    assert missing_obl == []
    assert missing_rec == []
