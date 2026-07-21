"""Backup before overwrite."""

import os
import re
import shutil
import time
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from devctl.utils.logging import ProgressBar, log_status, log_verbose
from devctl.utils.shell import get_backups_dir


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _get_dir_size(path: Path) -> int:
    """Get total size of directory in bytes."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except (OSError, PermissionError):
        pass
    return total


def _copytree_with_progress(
    src: Path,
    dst: Path,
    total_size: int,
) -> None:
    """Copy directory tree with progress bar."""
    progress = ProgressBar(total_size, desc="Copying")

    def copy_with_progress(src_file: str, dst_file: str) -> None:
        """Copy a single file and update progress."""
        shutil.copy2(src_file, dst_file)
        try:
            size = os.path.getsize(src_file)
            progress.update(size)
        except OSError:
            pass

    shutil.copytree(src, dst, copy_function=copy_with_progress)
    progress.finish()

_BACKUP_TIMESTAMP_SUFFIX = re.compile(r"^(.+)-(\d{8}T\d+Z)$")
_DEFAULT_RETENTION_COUNT = 3


def _backup_timestamp() -> str:
    """UTC timestamp with microsecond precision to avoid collisions within one apply run."""
    now = datetime.now(UTC)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z"


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
    """Parse '<slug>-<YYYYMMDDTHHMMSS[ffffff]Z>' backup directory names."""
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
    """Backup existing target to ~/.devctl/backups/<slug>-<timestamp>/. Returns backup path or None if nothing to backup.

    Symlinks are backed up as link metadata only (no deep copy of the resolved tree).
    """
    # lexists: include broken symlinks (Path.exists() follows and would skip them)
    if not target_path.exists() and not target_path.is_symlink():
        return None

    backups_dir = get_backups_dir()
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _backup_timestamp()
    backup_path = backups_dir / f"{slug}-{timestamp}"

    if target_path.is_symlink():
        log_status(f"Backing up symlink {target_path}...")
        start = time.monotonic()
        backup_path.mkdir(parents=True, exist_ok=True)
        link_dest = os.readlink(target_path)
        (backup_path / "SYMLINK_TARGET").write_text(link_dest, encoding="utf-8")
        elapsed = time.monotonic() - start
        log_status(f"Backup complete ({elapsed:.1f}s) → {backup_path.name}")
    elif target_path.is_dir():
        size = _get_dir_size(target_path)
        size_str = _format_size(size)
        log_status(f"Backing up {target_path} ({size_str})...")
        start = time.monotonic()
        _copytree_with_progress(target_path, backup_path, size)
        elapsed = time.monotonic() - start
        log_status(f"Backup complete ({elapsed:.1f}s) → {backup_path.name}")
    else:
        log_status(f"Backing up {target_path}...")
        start = time.monotonic()
        backup_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path / target_path.name)
        elapsed = time.monotonic() - start
        log_status(f"Backup complete ({elapsed:.1f}s)")

    log_verbose(f"Backup saved to {backup_path}")
    return backup_path
