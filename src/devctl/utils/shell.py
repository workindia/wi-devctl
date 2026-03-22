"""Shell detection and path expansion utilities."""

import os
from pathlib import Path


def expand_path(path: str) -> Path:
    """Expand ~ and environment variables in a path."""
    expanded = os.path.expandvars(os.path.expanduser(path))
    return Path(expanded)


def get_devctl_home() -> Path:
    """Return the devctl home directory (~/.devctl)."""
    return expand_path("~/.devctl")


def get_repos_dir() -> Path:
    """Return the repos directory (~/.devctl/repos)."""
    return get_devctl_home() / "repos"


def get_backups_dir() -> Path:
    """Return the backups directory (~/.devctl/backups)."""
    return get_devctl_home() / "backups"


def get_state_path() -> Path:
    """Return the state.json path (~/.devctl/state.json)."""
    return get_devctl_home() / "state.json"
