"""Protocol parsing and execution."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from devctl.core.backup import backup_apply_run, prune_backups, restore_apply_run
from devctl.utils.logging import log_status, log_verbose
from devctl.utils.shell import expand_path
from devctl.utils.yaml_loader import load_yaml


@dataclass
class Protocol:
    """Single protocol definition."""

    name: str
    type: str
    source: str
    target: str
    obligations: list[str]
    recommendations: list[str]


_PROTOCOL_NAMES = ("protocol.yaml", "protocol.yml")


def load_protocols(repo_path: Path) -> tuple[str, list[Protocol]]:
    """Load and validate protocol.yaml or protocol.yml from repo. Returns (version, protocols)."""
    protocol_file = None
    for name in _PROTOCOL_NAMES:
        candidate = repo_path / name
        if candidate.exists():
            protocol_file = candidate
            break

    if protocol_file is None:
        raise FileNotFoundError(
            f"protocol.yaml or protocol.yml not found in {repo_path}\n"
            "Add protocol.yaml (or protocol.yml) to the repo root. See examples/protocol.yaml for the format."
        )

    log_verbose(f"Loading protocol from {protocol_file.name}")
    data = load_yaml(protocol_file)
    if not data or not isinstance(data, dict):
        raise ValueError("protocol file must be a non-empty object")

    version = str(data.get("version", "v1"))
    protocols_data = data.get("protocols", [])
    if not isinstance(protocols_data, list):
        raise ValueError("protocols must be a list")

    protocols: list[Protocol] = []
    for i, p in enumerate(protocols_data):
        if not isinstance(p, dict):
            raise ValueError(f"protocol[{i}] must be an object")
        name = p.get("name")
        ptype = p.get("type")
        source = p.get("source")
        target = p.get("target")
        if not all([name, ptype, source, target]):
            raise ValueError(f"protocol[{i}] requires name, type, source, target")
        protocols.append(
            Protocol(
                name=str(name),
                type=str(ptype),
                source=str(source),
                target=str(target),
                obligations=list(p.get("obligations") or []),
                recommendations=list(p.get("recommendations") or []),
            )
        )

    return version, protocols


def _remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory tree at path."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _clear_conflicting_targets(source_path: Path, target_path: Path) -> None:
    """Remove target paths that would block a merge copy (symlinks, type mismatches)."""
    if source_path.is_file():
        if target_path.is_symlink() or (target_path.exists() and target_path.is_dir()):
            log_verbose(f"Removing conflicting target before file sync: {target_path}")
            _remove_path(target_path)
        return

    if not source_path.is_dir():
        return

    for child in source_path.iterdir():
        dest = target_path / child.name
        if not (dest.exists() or dest.is_symlink()):
            continue
        # Symlink at dest always conflicts with copying real content into that name
        if dest.is_symlink():
            log_verbose(f"Removing symlink before file_sync merge: {dest}")
            _remove_path(dest)
            continue
        # Source dir vs target file (or vice versa)
        if child.is_dir() and dest.is_file():
            log_verbose(f"Removing file blocking directory sync: {dest}")
            _remove_path(dest)
        elif child.is_file() and dest.is_dir() and not dest.is_symlink():
            log_verbose(f"Removing directory blocking file sync: {dest}")
            _remove_path(dest)


def _file_sync(
    source_path: Path,
    target_path: Path,
) -> tuple[list[str], list[str]]:
    """Execute file_sync: merge source into target. Never deletes unrelated existing files."""
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.is_symlink():
        log_verbose(f"Removing symlink target before file_sync: {target_path}")
        _remove_path(target_path)

    _clear_conflicting_targets(source_path, target_path)

    if source_path.is_dir():
        log_status(f"Syncing {source_path.name}/ → {target_path}")
        log_verbose(f"Merging directory {source_path} -> {target_path} (existing files preserved)")
        shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        log_status("Sync complete")
    else:
        log_status(f"Syncing {source_path.name} → {target_path}")
        log_verbose(f"Copying file {source_path} -> {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        log_status("Sync complete")

    return [], []


def _symlink_points_to(target_path: Path, expected: Path) -> bool:
    """Return True if target_path is a symlink whose destination resolves to expected."""
    if not target_path.is_symlink():
        return False
    try:
        return target_path.resolve() == expected.resolve()
    except OSError:
        return False


def _symlink_sync(
    source_path: Path,
    target_path: Path,
) -> tuple[list[str], list[str]]:
    """Ensure target_path is a symlink to source_path (absolute). Idempotent; migrates real dirs."""
    expected = source_path.resolve()

    if _symlink_points_to(target_path, expected):
        log_verbose(f"Symlink already correct: {target_path} -> {expected}")
        log_status(f"Link ok {target_path.name}/ → {expected}")
        return [], []

    exists_or_link = target_path.exists() or target_path.is_symlink()
    if exists_or_link:
        log_verbose(f"Removing existing path at {target_path}")
        _remove_path(target_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    log_status(f"Linking {target_path} → {expected}")
    target_path.symlink_to(expected, target_is_directory=source_path.is_dir())
    log_status("Link complete")
    return [], []


def check_symlink_integrity(
    protocol: Protocol,
    repo_path: Path,
) -> str | None:
    """For symlink_sync protocols, return an error message if the link is missing/wrong; else None."""
    if protocol.type != "symlink_sync":
        return None
    source_path = (repo_path / protocol.source).resolve()
    target_path = expand_path(protocol.target)
    if not target_path.is_symlink():
        if target_path.exists():
            return f"{target_path} exists but is not a symlink (expected -> {source_path})"
        return f"{target_path} missing (expected symlink -> {source_path})"
    if not _symlink_points_to(target_path, source_path):
        try:
            current = os.readlink(target_path)
        except OSError:
            current = "(unreadable)"
        return f"{target_path} points to {current}, expected {source_path}"
    return None


def execute_protocol(
    protocol: Protocol,
    repo_path: Path,
    slug: str,
    do_backup: bool = True,
) -> tuple[list[str], list[str]]:
    """Execute a single protocol. Returns (missing_obligations, missing_recommendations).

    do_backup is accepted for API compatibility but ignored: apply_protocols takes a
    single run-level snapshot before executing protocols.
    """
    del slug, do_backup  # run-level backup owns snapshots
    source_path = (repo_path / protocol.source).resolve()
    target_path = expand_path(protocol.target)

    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if protocol.type == "file_sync":
        missing_obl, missing_rec = _file_sync(source_path, target_path)
    elif protocol.type == "symlink_sync":
        missing_obl, missing_rec = _symlink_sync(source_path, target_path)
    else:
        raise ValueError(f"Unknown protocol type: {protocol.type}")

    # Check obligations (paths relative to target)
    for rel in protocol.obligations:
        full = target_path / rel
        if not full.exists():
            missing_obl.append(str(full))

    # Check recommendations
    for rel in protocol.recommendations:
        full = target_path / rel
        if not full.exists():
            missing_rec.append(str(full))

    return missing_obl, missing_rec


def apply_protocols(
    repo_path: Path,
    slug: str,
    do_backup: bool = True,
) -> tuple[str, list[Protocol], list[str], list[str]]:
    """Load and apply all protocols. Returns (version, protocols, missing_obligations, missing_recommendations).

    When do_backup is True, takes one run-level snapshot of all protocol targets before
    applying. On failure, restores that snapshot and re-raises. On success, prunes old runs.
    """
    version, protocols = load_protocols(repo_path)
    log_status(f"Applying {len(protocols)} protocol(s)...")
    log_verbose(f"Applying {len(protocols)} protocol(s)")
    all_missing_obl: list[str] = []
    all_missing_rec: list[str] = []

    run_dir = None
    if do_backup:
        targets = [expand_path(p.target) for p in protocols]
        run_dir = backup_apply_run(targets, slug)

    try:
        for i, protocol in enumerate(protocols, 1):
            log_status(f"[{i}/{len(protocols)}] Protocol '{protocol.name}' ({protocol.type})")
            log_verbose(
                f"Executing protocol '{protocol.name}' ({protocol.type}): "
                f"{protocol.source} -> {protocol.target}"
            )
            obl, rec = execute_protocol(protocol, repo_path, slug, do_backup=False)
            all_missing_obl.extend(obl)
            all_missing_rec.extend(rec)
    except Exception:
        if run_dir is not None:
            try:
                restore_apply_run(run_dir)
            except Exception as restore_err:
                log_status(f"Restore after failure also failed: {restore_err}")
        raise

    if do_backup:
        prune_backups(slug)

    return version, protocols, all_missing_obl, all_missing_rec
