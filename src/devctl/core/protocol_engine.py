"""Protocol parsing and execution."""

from dataclasses import dataclass, field
import subprocess
from pathlib import Path

from devctl.core.backup import backup_target, prune_backups
from devctl.utils.logging import log_verbose
from devctl.utils.shell import expand_path
from devctl.utils.yaml_loader import load_yaml
import shutil
import logging
logger = logging.getLogger(__name__)



@dataclass
class Protocol:
    """Single protocol definition."""

    name: str
    type: str
    source: str = ""
    target: str = ""
    script: str = ""
    obligations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


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
        source = p.get("source", "")
        target = p.get("target", "")
        script = p.get("script", "")

        if not all([name, ptype]):
            raise ValueError(f"protocol[{i}] requires name and type")
        if ptype == "file_sync" and not all([source, target]):
            raise ValueError(f"protocol[{i}] requires source and target for file_sync")
        if ptype == "script_run" and not script:
            raise ValueError(f"protocol[{i}] requires script for script_run")
        protocols.append(
            Protocol(
                name=str(name),
                type=str(ptype),
                source=str(source),
                target=str(target),
                script=str(script),
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

        log_verbose(f"Merging directory {source_path} -> {target_path} (existing files preserved)")
        shutil.copytree(source_path, target_path, dirs_exist_ok=True)
    else:
        log_verbose(f"Copying file {source_path} -> {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(source_path, target_path)

    return [], []


def _script_run(script: str, repo_path: Path, protocol_name: str) -> tuple[list[str], list[str]]:
    """Execute script_run: run a shell command from the repo root."""
    if not script.strip():
        raise ValueError(f"script_run protocol '{protocol_name}' requires a non-empty script")

    log_verbose(f"Running script_run '{protocol_name}' in {repo_path}: {script}")


    proc = subprocess.run(
        script,
        cwd=repo_path,
        shell=True,
        capture_output=True,
        text=True,
    )

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if stdout:
        log_verbose(f"script_run '{protocol_name}' stdout:\n{stdout}")

    if stderr:
        log_verbose(f"script_run '{protocol_name}' stderr:\n{stderr}")

    if proc.returncode != 0:
        parts = [
            f"script_run failed for '{protocol_name}' (exit code {proc.returncode})",
            f"command: {script}",
        ]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        raise RuntimeError("\n".join(parts))

    return [], []


def execute_protocol(
    protocol: Protocol,
    repo_path: Path,
    slug: str,
    do_backup: bool = True,
) -> tuple[list[str], list[str]]:
    """Execute a single protocol. Returns (missing_obligations, missing_recommendations)."""
    if protocol.type == "file_sync":
        source_path = (repo_path / protocol.source).resolve()
        target_path = expand_path(protocol.target)
        if not source_path.exists():
            raise FileNotFoundError(f"Source not found: {source_path}")
        missing_obl, missing_rec = _file_sync(source_path, target_path, slug, do_backup)
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
    elif protocol.type == "script_run":
        missing_obl, missing_rec = _script_run(protocol.script, repo_path, protocol.name)
    else:
        raise ValueError(f"Unknown protocol type: {protocol.type}")

    return missing_obl, missing_rec


def apply_protocols(
    repo_path: Path,
    slug: str,
    do_backup: bool = True,
) -> tuple[str, list[Protocol], list[str], list[str]]:
    """Load and apply all protocols. Returns (version, protocols, missing_obligations, missing_recommendations)."""
    version, protocols = load_protocols(repo_path)
    log_verbose(f"Applying {len(protocols)} protocol(s)")
    all_missing_obl: list[str] = []
    all_missing_rec: list[str] = []

    for protocol in protocols:
        if protocol.type == "script_run":
            log_verbose(f"Executing protocol '{protocol.name}' ({protocol.type}): {protocol.script}")
        else:
            log_verbose(
                f"Executing protocol '{protocol.name}' ({protocol.type}): "
                f"{protocol.source} -> {protocol.target}"
            )
        obl, rec = execute_protocol(protocol, repo_path, slug, do_backup)
        all_missing_obl.extend(obl)
        all_missing_rec.extend(rec)

    if do_backup:
        prune_backups(slug)

    return version, protocols, all_missing_obl, all_missing_rec
