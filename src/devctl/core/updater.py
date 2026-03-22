"""Self-update logic."""

import json
import os
import platform
import sys
import tempfile
from typing import Tuple
from urllib.error import HTTPError
from urllib.request import urlopen

from devctl import __version__
from devctl.utils.logging import log_error


def _get_platform_key() -> str:
    """Return platform key for manifest downloads (e.g. darwin-arm64)."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine
    os_map = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    os_name = os_map.get(system, system)
    return f"{os_name}-{arch}"


def _fetch_manifest(manifest_url: str | None) -> dict | None:
    """Fetch manifest from URL or GitHub API. Returns None on failure."""
    if manifest_url:
        try:
            with urlopen(manifest_url, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            log_error(f"Failed to fetch manifest from {manifest_url}: {e}")
            return None

    # Default: GitHub Releases API
    repo = os.environ.get("DEVCTL_GITHUB_REPO", "wi-devctl")
    owner = os.environ.get("DEVCTL_GITHUB_OWNER", "WorkIndia-Private")
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        with urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        # Convert GitHub release to manifest format
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
        tag = data.get("tag_name", "v0.0.0")
        # Map platform keys to asset names (e.g. devctl-darwin-arm64)
        downloads = {}
        for name, url in assets.items():
            if name.startswith("devctl-") and not name.endswith(".json"):
                # devctl-darwin-arm64 -> darwin-arm64
                key = name.replace("devctl-", "", 1).rsplit(".", 1)[0]
                downloads[key] = url
        return {"latest_version": tag, "downloads": downloads}
    except HTTPError as e:
        if e.code == 404:
            # No releases yet or wrong owner/repo - skip silently
            return None
        log_error(f"Failed to fetch GitHub release: {e}")
        return None
    except Exception as e:
        log_error(f"Failed to fetch GitHub release: {e}")
        return None


def check_for_update(manifest_url: str | None) -> Tuple[bool, str, str | None]:
    """Check if update is available. Returns (has_update, latest_version, download_url)."""
    manifest = _fetch_manifest(manifest_url)
    if not manifest:
        return False, __version__, None

    latest = manifest.get("latest_version", "")
    downloads = manifest.get("downloads", {})
    platform_key = _get_platform_key()
    download_url = downloads.get(platform_key)

    if not download_url:
        return False, __version__, None

    # Compare versions (strip 'v' for comparison)
    def norm(v: str) -> str:
        return v.lstrip("v")

    if norm(latest) > norm(__version__):
        return True, latest, download_url
    return False, latest, download_url


def perform_update(manifest_url: str | None, force: bool = False) -> Tuple[bool, str, str | None]:
    """Check for update and perform it if available. On success, re-execs (never returns).
    Returns (has_update, latest_version, download_url) when no update performed."""
    has_update, latest_version, download_url = check_for_update(manifest_url)

    if not has_update and not force:
        return False, latest_version or __version__, None

    if not download_url:
        if force:
            log_error("No download URL for this platform.")
        return False, latest_version or __version__, None

    if not has_update and force:
        # Force but already current - still try to re-download?
        # For force we re-download anyway
        pass

    # Download and replace
    try:
        with urlopen(download_url, timeout=60) as resp:
            new_binary = resp.read()
    except Exception as e:
        log_error(f"Failed to download update: {e}")
        return False, latest_version, None

    exe = sys.executable
    # When running as PyInstaller binary, sys.executable is the binary path
    if getattr(sys, "frozen", False):
        exe = sys.executable
    else:
        # Running from source - can't replace self
        log_error("Auto-update only works when running the installed binary.")
        return False, latest_version, None

    try:
        fd, path = tempfile.mkstemp(suffix=".devctl", prefix="devctl-")
        try:
            os.write(fd, new_binary)
            os.close(fd)
            os.chmod(path, 0o755)
            # Atomic replace
            os.replace(path, exe)
        except Exception:
            os.close(fd)
            if os.path.exists(path):
                os.unlink(path)
            raise
    except Exception as e:
        log_error(f"Failed to replace binary: {e}")
        return False, latest_version, None

    # Re-exec
    os.execv(exe, [exe] + sys.argv[1:])
    return True, latest_version, download_url  # Unreachable
