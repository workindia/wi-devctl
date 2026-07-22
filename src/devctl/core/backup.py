"""Backup before overwrite — one snapshot per apply run."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from devctl.utils.logging import ProgressBar, log_status, log_verbose
from devctl.utils.shell import get_backups_dir

_RUN_NAME = re.compile(r"^(.+)-run-(\d{8}T\d+Z)$")
# Legacy per-protocol backups: <slug>-<timestamp> without "-run-"
_LEGACY_BACKUP_NAME = re.compile(r"^(.+)-(\d{8}T\d+Z)$")
_DEFAULT_RETENTION_COUNT = 3
_MANIFEST_NAME = "manifest.json"
_SYMLINK_META = "SYMLINK_TARGET"


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _get_dir_size(path: Path) -> int:
    """Get total size of directory in bytes (follows symlinks for size estimate)."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_symlink():
                continue
            if entry.is_file():
                total += entry.stat().st_size
    except (OSError, PermissionError):
        pass
    return total


def _copytree_with_progress(
    src: Path,
    dst: Path,
    total_size: int,
    *,
    symlinks: bool = False,
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

    shutil.copytree(
        src,
        dst,
        symlinks=symlinks,
        copy_function=copy_with_progress,
    )
    progress.finish()


def _backup_timestamp() -> str:
    """UTC timestamp with second precision (YYYYMMDDTHHMMSSZ)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


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


def _parse_run_backup_name(name: str) -> tuple[str, str] | None:
    """Parse '<slug>-run-<YYYYMMDDTHHMMSSZ>' backup directory names.

    Also accepts older names that included microseconds in the timestamp.
    """
    match = _RUN_NAME.match(name)
    if not match:
        return None
    return match.group(1), match.group(2)


def _parse_legacy_backup_name(name: str) -> tuple[str, str] | None:
    """Parse legacy '<slug>-<timestamp>' names (not run backups)."""
    if "-run-" in name:
        return None
    match = _LEGACY_BACKUP_NAME.match(name)
    if not match:
        return None
    return match.group(1), match.group(2)


def _parse_backup_name(name: str) -> tuple[str, str] | None:
    """Parse run or legacy backup directory names. Prefer run format."""
    parsed = _parse_run_backup_name(name)
    if parsed:
        return parsed
    return _parse_legacy_backup_name(name)


def _path_is_under(child: Path, parent: Path) -> bool:
    """Return True if child is the same as parent or a descendant."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def dedupe_backup_targets(targets: Sequence[Path]) -> list[Path]:
    """Drop targets nested under another target (ancestor covers children)."""
    # Resolve for comparison; keep original Path objects for existence checks
    unique: list[Path] = []
    seen: set[str] = set()
    for t in targets:
        key = str(t)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)

    # Prefer shorter / ancestor paths: sort by path string length then lexicographically
    ordered = sorted(unique, key=lambda p: (len(str(p.resolve())), str(p.resolve())))
    kept: list[Path] = []
    for path in ordered:
        if any(_path_is_under(path, ancestor) for ancestor in kept):
            continue
        kept.append(path)
    return kept


def _remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory tree at path."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _write_entry(target_path: Path, entry_dir: Path) -> str:
    """Snapshot one target into entry_dir. Returns kind: dir|file|symlink."""
    entry_dir.mkdir(parents=True, exist_ok=True)
    if target_path.is_symlink():
        link_dest = os.readlink(target_path)
        (entry_dir / _SYMLINK_META).write_text(link_dest, encoding="utf-8")
        return "symlink"
    if target_path.is_dir():
        size = _get_dir_size(target_path)
        # Copy symlink nodes as links so broken nested links do not fail the run snapshot
        content = entry_dir / "content"
        _copytree_with_progress(target_path, content, size, symlinks=True)
        return "dir"
    shutil.copy2(target_path, entry_dir / target_path.name)
    return "file"


def backup_apply_run(targets: Sequence[Path], slug: str) -> Path | None:
    """Snapshot unique protocol targets once into ~/.devctl/backups/<slug>-run-<ts>/.

    Returns the run backup directory, or None if nothing existed to snapshot.
    Nested targets under an ancestor path are skipped (ancestor covers them).
    """
    to_backup = [
        t
        for t in dedupe_backup_targets(list(targets))
        if t.exists() or t.is_symlink()
    ]
    if not to_backup:
        return None

    backups_dir = get_backups_dir()
    backups_dir.mkdir(parents=True, exist_ok=True)
    # Second-precision names: if a run already exists this second, wait for the next.
    run_dir: Path | None = None
    for _ in range(3):
        timestamp = _backup_timestamp()
        candidate = backups_dir / f"{slug}-run-{timestamp}"
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            run_dir = candidate
            break
        except FileExistsError:
            time.sleep(1)
    if run_dir is None:
        raise RuntimeError(f"Could not create unique run backup dir for slug {slug}")

    log_status(f"Run backup: snapshotting {len(to_backup)} target(s)...")
    start = time.monotonic()
    manifest: list[dict[str, str]] = []

    for i, target_path in enumerate(to_backup):
        entry_id = str(i)
        entry_dir = run_dir / entry_id
        log_verbose(f"Run backup entry {entry_id}: {target_path}")
        kind = _write_entry(target_path, entry_dir)
        manifest.append(
            {
                "path": str(target_path),
                "entry": entry_id,
                "kind": kind,
            }
        )

    (run_dir / _MANIFEST_NAME).write_text(
        json.dumps({"targets": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    elapsed = time.monotonic() - start
    log_status(f"Run backup complete ({elapsed:.1f}s) → {run_dir.name}")
    log_verbose(f"Run backup saved to {run_dir}")
    return run_dir


def restore_apply_run(run_dir: Path) -> None:
    """Restore all targets recorded in a run backup directory."""
    manifest_path = run_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run backup manifest missing: {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = data.get("targets") or []
    if not isinstance(targets, list):
        raise ValueError(f"Invalid run backup manifest: {manifest_path}")

    log_status(f"Restoring run backup {run_dir.name} ({len(targets)} target(s))...")
    for item in targets:
        if not isinstance(item, dict):
            continue
        path_str = item.get("path")
        entry_id = item.get("entry")
        kind = item.get("kind")
        if not path_str or entry_id is None or not kind:
            continue
        target_path = Path(path_str)
        entry_dir = run_dir / str(entry_id)
        if not entry_dir.exists():
            log_verbose(f"Skipping missing entry {entry_id} for {target_path}")
            continue

        if target_path.exists() or target_path.is_symlink():
            _remove_path(target_path)

        target_path.parent.mkdir(parents=True, exist_ok=True)

        if kind == "symlink":
            link_dest = (entry_dir / _SYMLINK_META).read_text(encoding="utf-8")
            target_path.symlink_to(link_dest)
        elif kind == "dir":
            content = entry_dir / "content"
            if content.exists():
                shutil.copytree(content, target_path, symlinks=True)
            else:
                # Backward-compatible: entry dir is the tree itself
                shutil.copytree(entry_dir, target_path, symlinks=True)
        elif kind == "file":
            files = [p for p in entry_dir.iterdir() if p.is_file()]
            if not files:
                raise FileNotFoundError(f"No file snapshot in {entry_dir}")
            shutil.copy2(files[0], target_path)
        else:
            raise ValueError(f"Unknown backup kind {kind!r} for {target_path}")

    log_status("Restore complete")


def prune_backups(
    slug: str | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Delete old run backups beyond the retention limit; remove legacy non-run backups.

    Keeps the newest DEVCTL_BACKUP_RETENTION_COUNT **run** backups per slug (default: 3).
    Legacy `<slug>-<timestamp>` folders (without `-run-`) for that slug are always pruned.
    Set DEVCTL_BACKUP_RETENTION_DISABLED=1 or DEVCTL_BACKUP_RETENTION_COUNT=0 to skip
    run retention pruning (legacy cleanup still runs when retention is enabled).

    Returns paths that were deleted (or would be deleted when dry_run=True).
    """
    retention = _backup_retention_count(env)
    if retention is None:
        return []

    backups_dir = get_backups_dir()
    if not backups_dir.exists():
        return []

    runs_by_slug: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    legacy: list[Path] = []

    for entry in backups_dir.iterdir():
        if not entry.is_dir():
            continue
        run_parsed = _parse_run_backup_name(entry.name)
        if run_parsed:
            entry_slug, timestamp = run_parsed
            if slug is not None and entry_slug != slug:
                continue
            runs_by_slug[entry_slug].append((timestamp, entry))
            continue
        legacy_parsed = _parse_legacy_backup_name(entry.name)
        if legacy_parsed:
            entry_slug, _ts = legacy_parsed
            if slug is not None and entry_slug != slug:
                continue
            legacy.append(entry)

    deleted: list[Path] = []

    for path in legacy:
        log_verbose(f"Pruning legacy backup: {path}")
        if not dry_run:
            shutil.rmtree(path)
        deleted.append(path)

    for _entry_slug, entries in runs_by_slug.items():
        entries.sort(key=lambda item: item[0], reverse=True)
        for _, path in entries[retention:]:
            log_verbose(f"Pruning old run backup: {path}")
            if not dry_run:
                shutil.rmtree(path)
            deleted.append(path)

    return deleted


def backup_target(target_path: Path, slug: str) -> Path | None:
    """Backup a single target via a one-entry run snapshot (compatibility helper).

    Prefer backup_apply_run for protocol applies.
    """
    return backup_apply_run([target_path], slug)
