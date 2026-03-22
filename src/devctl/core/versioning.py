"""Version tracking in state.json."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from devctl.utils.shell import get_state_path


def load_state() -> dict[str, Any]:
    """Load state.json. Returns empty dict if not found."""
    path = get_state_path()
    if not path.exists():
        return {"repos": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {"repos": {}}


def save_state(state: dict[str, Any]) -> None:
    """Save state.json."""
    path = get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_repo_version(repo_path: Path) -> str:
    """Read version from repo (VERSION file or protocol.yaml/yml)."""
    version_file = repo_path / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    from devctl.core.protocol_engine import _PROTOCOL_NAMES

    for name in _PROTOCOL_NAMES:
        protocol_file = repo_path / name
        if protocol_file.exists():
            from devctl.utils.yaml_loader import load_yaml

            data = load_yaml(protocol_file)
            if data and isinstance(data, dict) and "version" in data:
                return str(data["version"])
            return "unknown"

    return "unknown"


def register_repo(slug: str, url: str, path: Path, version: str) -> None:
    """Register repo in state.json."""
    state = load_state()
    if "repos" not in state:
        state["repos"] = {}
    state["repos"][slug] = {
        "url": url,
        "path": str(path),
        "version": version,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_state(state)


def list_repos() -> dict[str, dict[str, Any]]:
    """List all registered repos."""
    state = load_state()
    return state.get("repos", {})
