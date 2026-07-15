"""Backup before overwrite."""

import os
import re
import shutil
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from devctl.utils.logging import log_verbose
from devctl.utils.shell import get_backups_dir

_BACKUP_TIMESTAMP_SUFFIX = re.compile(r"^(.+)-(\d{8}T\d{6}Z)$")
_DEFAULT_RETENTION_COUNT = 3


def _backup_retention_count(env: Mapping[str, str] | None = None) -> int | None:
    """Return how many backups to keep per slug, or None to disable pruning."""
    e = os.environ if env is None else env
    if e.get("DEVCTL_BACKUP_RETENTION_DISABLED") == "1":
        return None

    raw = e.get("DEVCTL_BACKUP_RETENTION_COUNT", str(_DEFAULT_RETENTION_COUNT))
    try:
        count = int(raw)
    except ValueError:
        count = _DEFAULT_RETENTION_COUNT

    if count <= 0:
        return None
    return count


def _parse_backup_name(name: str) -> tuple[str, str] | None:
    """Parse '<slug>-<YYYYMMDDTHHMMSSZ>' backup directory names."""
    match = _BACKUP_TIMESTAMP_SUFFIX.match(name)
    if not match:
        return None
    return match.group(1), match.group(2)


def prune_backups(
    slug: str | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Delete old backups beyond the retention limit.

    Keeps the newest DEVCTL_BACKUP_RETENTION_COUNT backups per slug (default: 3).
    Set DEVCTL_BACKUP_RETENTION_DISABLED=1 or DEVCTL_BACKUP_RETENTION_COUNT=0 to skip pruning.

    Returns paths that were deleted (or would be deleted when dry_run=True).
    """
    retention = _backup_retention_count(env)
    if retention is None:
        return []

    backups_dir = get_backups_dir()
    if not backups_dir.exists():
        return []

    by_slug: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for entry in backups_dir.iterdir():
        if not entry.is_dir():
            continue
        parsed = _parse_backup_name(entry.name)
        if not parsed:
            continue
        entry_slug, timestamp = parsed
        if slug is not None and entry_slug != slug:
            continue
        by_slug[entry_slug].append((timestamp, entry))

    deleted: list[Path] = []
    for _entry_slug, entries in by_slug.items():
        entries.sort(key=lambda item: item[0], reverse=True)
        for _, path in entries[retention:]:
            log_verbose(f"Pruning old backup: {path}")
            if not dry_run:
                shutil.rmtree(path)
            deleted.append(path)

    return deleted


def backup_target(target_path: Path, slug: str) -> Path | None:
    """Backup existing target to ~/.devctl/backups/<slug>-<timestamp>/. Returns backup path or None if nothing to backup."""
    if not target_path.exists():
        return None

    backups_dir = get_backups_dir()
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"{slug}-{timestamp}"
    log_verbose(f"Backup created at {backup_path}")

    if target_path.is_dir():
        shutil.copytree(target_path, backup_path)
    else:
        backup_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path / target_path.name)

    return backup_path
