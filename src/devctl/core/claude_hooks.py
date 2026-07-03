"""claude_hooks protocol: sync hook definitions into ~/.claude/settings.json."""

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from devctl.utils.logging import log_verbose
from devctl.utils.shell import get_devctl_home


_HOOKS_YAML_NAME = "hooks.yaml"


def _load_hooks_yaml(source_path: Path) -> dict[str, Any]:
    hooks_file = source_path / _HOOKS_YAML_NAME
    if not hooks_file.exists():
        return {}
    with open(hooks_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _load_settings(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}
    with open(settings_path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _write_settings(settings_path: Path, data: dict[str, Any]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _copy_scripts(source_path: Path, scripts_dest: Path) -> None:
    """Copy non-hooks.yaml files from source into scripts_dest."""
    scripts_dest.mkdir(parents=True, exist_ok=True)
    for item in source_path.iterdir():
        if item.name == _HOOKS_YAML_NAME:
            continue
        if item.is_file():
            dest = scripts_dest / item.name
            shutil.copy2(item, dest)
            log_verbose(f"Copied hook script {item.name} -> {dest}")


def sync_claude_hooks(
    source_path: Path,
    settings_path: Path,
    scripts_dest: Path | None = None,
) -> None:
    """Sync hooks from source_path into settings_path (~/.claude/settings.json).

    1. Copies non-hooks.yaml files from source_path into scripts_dest
       (defaults to ~/.devctl/hooks/).
    2. Reads source_path/hooks.yaml and replaces the 'hooks' key in
       settings_path with its content. All other existing settings are
       preserved.
    3. If hooks.yaml is absent or contains no 'hooks' key, the 'hooks'
       key is removed from settings_path (clean uninstall on next sync).
    """
    if scripts_dest is None:
        scripts_dest = get_devctl_home() / "hooks"

    log_verbose(f"Syncing claude hooks: {source_path} -> {settings_path}")

    _copy_scripts(source_path, scripts_dest)

    hooks_data = _load_hooks_yaml(source_path)
    hooks_config = hooks_data.get("hooks")

    settings = _load_settings(settings_path)

    if hooks_config:
        log_verbose(f"Installing hooks config into {settings_path}")
        settings["hooks"] = hooks_config
    else:
        log_verbose(f"No hooks defined — removing 'hooks' key from {settings_path}")
        settings.pop("hooks", None)

    _write_settings(settings_path, settings)
    log_verbose("claude_hooks sync complete")
