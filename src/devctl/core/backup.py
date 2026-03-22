"""Backup before overwrite."""

import shutil
from datetime import datetime
from pathlib import Path

from devctl.utils.logging import log_verbose
from devctl.utils.shell import get_backups_dir


def backup_target(target_path: Path, slug: str) -> Path | None:
    """Backup existing target to ~/.devctl/backups/<slug>-<timestamp>/. Returns backup path or None if nothing to backup."""
    if not target_path.exists():
        return None

    backups_dir = get_backups_dir()
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{slug}-{timestamp}"
    log_verbose(f"Backup created at {backup_path}")

    if target_path.is_dir():
        shutil.copytree(target_path, backup_path)
    else:
        backup_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path / target_path.name)

    return backup_path
