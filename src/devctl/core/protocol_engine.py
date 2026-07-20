"""Protocol parsing and execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from devctl.core.backup import backup_target, prune_backups
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


def _file_sync(
    source_path: Path,
    target_path: Path,
    slug: str,
    do_backup: bool = True,
) -> tuple[list[str], list[str]]:
    """Execute file_sync: merge source into target. Never deletes existing files/folders in target."""
    if do_backup and target_path.exists():
        log_verbose(f"Backing up existing {target_path}")
        backup_target(target_path, slug)

    target_path.parent.mkdir(parents=True, exist_ok=True)

    if source_path.is_dir():
        import shutil

        log_status(f"Syncing {source_path.name}/ → {target_path}")
        log_verbose(f"Merging directory {source_path} -> {target_path} (existing files preserved)")
        shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        log_status("Sync complete")
    else:
        log_status(f"Syncing {source_path.name} → {target_path}")
        log_verbose(f"Copying file {source_path} -> {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(source_path, target_path)
        log_status("Sync complete")

    return [], []


def execute_protocol(
    protocol: Protocol,
    repo_path: Path,
    slug: str,
    do_backup: bool = True,
) -> tuple[list[str], list[str]]:
    """Execute a single protocol. Returns (missing_obligations, missing_recommendations)."""
    source_path = (repo_path / protocol.source).resolve()
    target_path = expand_path(protocol.target)

    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if protocol.type == "file_sync":
        missing_obl, missing_rec = _file_sync(source_path, target_path, slug, do_backup)
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
    """Load and apply all protocols. Returns (version, protocols, missing_obligations, missing_recommendations)."""
    version, protocols = load_protocols(repo_path)
    log_status(f"Applying {len(protocols)} protocol(s)...")
    log_verbose(f"Applying {len(protocols)} protocol(s)")
    all_missing_obl: list[str] = []
    all_missing_rec: list[str] = []

    for i, protocol in enumerate(protocols, 1):
        log_status(f"[{i}/{len(protocols)}] Protocol '{protocol.name}' ({protocol.type})")
        log_verbose(f"Executing protocol '{protocol.name}' ({protocol.type}): {protocol.source} -> {protocol.target}")
        obl, rec = execute_protocol(protocol, repo_path, slug, do_backup)
        all_missing_obl.extend(obl)
        all_missing_rec.extend(rec)

    if do_backup:
        prune_backups(slug)

    return version, protocols, all_missing_obl, all_missing_rec
