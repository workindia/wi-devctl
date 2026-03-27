"""Recurring config repo sync - check for new pushes and pull + re-apply."""

from collections.abc import Mapping
import os
import time
from pathlib import Path

from devctl.core.protocol_engine import apply_protocols
from devctl.core.repo_manager import clone_or_pull, fetch_and_has_updates
from devctl.core.versioning import list_repos, register_repo
from devctl.utils.logging import log_error, log_verbose
from devctl.utils.shell import get_devctl_home

def _config_sync_interval_seconds(
    env: Mapping[str, str] | None = None,
) -> float:
    """Parse sync interval from env: minutes win if set; else hours (default 1 h).

    Fractional values are allowed for both units.
    """
    e = os.environ if env is None else env
    raw_mins = e.get("DEVCTL_CONFIG_SYNC_INTERVAL_MINUTES")
    if raw_mins is not None and str(raw_mins).strip() != "":
        return float(raw_mins) * 60
    return float(e.get("DEVCTL_CONFIG_SYNC_INTERVAL_HOURS", "1")) * 3600


# Seconds between automatic config sync checks (default: 1 hour).
_CONFIG_SYNC_INTERVAL = _config_sync_interval_seconds()
_LAST_SYNC_FILE = get_devctl_home() / ".last_config_sync"


def _is_sync_due() -> bool:
    """Return True if enough time has passed since the last config sync check."""
    if os.environ.get("DEVCTL_SKIP_CONFIG_SYNC") == "1":
        return False
    try:
        if _LAST_SYNC_FILE.exists():
            last = float(_LAST_SYNC_FILE.read_text().strip())
            if time.time() - last < _CONFIG_SYNC_INTERVAL:
                return False
    except Exception:
        pass
    return True


def _record_sync() -> None:
    """Write current timestamp to the last-sync file."""
    try:
        _LAST_SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_SYNC_FILE.write_text(str(time.time()))
    except Exception:
        pass


def perform_config_sync(
    force: bool = False,
    notify: bool = True,
) -> list[str]:
    """Check managed repos for new pushes; pull and re-apply when updates exist.

    Runs for each managed repo (from --repo in ai-kit setup). Rate-limited to
    once per DEVCTL_CONFIG_SYNC_INTERVAL_MINUTES if set, else
    DEVCTL_CONFIG_SYNC_INTERVAL_HOURS (default: 1 h; fractional values ok).
    Pass force=True to bypass (e.g. for background/cron).

    Returns the list of repo slugs that were updated.
    """
    repos = list_repos()
    if not repos:
        log_verbose("config sync: no managed repos in state")
        return []

    if not force and not _is_sync_due():
        log_verbose("config sync: skipped (rate limit; use force or wait)")
        return []

    _record_sync()
    updated_slugs: list[str] = []
    log_verbose(f"config sync: checking {len(repos)} repo(s)")

    for slug, info in repos.items():
        url = info.get("url")
        path_str = info.get("path")
        if not url or not path_str:
            log_verbose(f"config sync: skip {slug} (missing url or path)")
            continue

        repo_path = Path(path_str)
        if not repo_path.exists():
            log_verbose(f"config sync: skip {slug} (path missing: {repo_path})")
            continue

        try:
            log_verbose(f"config sync: checking {slug}")
            if not fetch_and_has_updates(repo_path):
                log_verbose(f"config sync: {slug} already up to date")
                continue

            log_verbose(f"Config sync: {slug} has new commits, pulling and re-applying")
            clone_or_pull(url)
            version, _, _obl, _rec = apply_protocols(repo_path, slug, do_backup=True)
            register_repo(slug, url, repo_path, version)
            updated_slugs.append(slug)
        except Exception as e:
            log_error(f"Config sync failed for {slug}: {e}")

    if updated_slugs and notify:
        from devctl.utils.notify import send_notification

        repos_str = ", ".join(updated_slugs)
        body = f"Pulled new config from: {repos_str}"
        send_notification("devctl", body)

    return updated_slugs
