"""Self-update logic."""

from devctl.utils.ssl_certs import configure_ssl_certs

configure_ssl_certs()

import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path
from typing import Tuple
from urllib.error import HTTPError
from urllib.request import Request

from devctl import __version__
from devctl.utils.logging import log_error
from devctl.utils.ssl_certs import open_url

# Seconds between automatic background update checks (default: 24 h).
_UPDATE_CHECK_INTERVAL = int(os.environ.get("DEVCTL_UPDATE_CHECK_INTERVAL_HOURS", "24")) * 3600
_LAST_CHECK_FILE = Path.home() / ".devctl" / ".last_update_check"


def _get_platform_key() -> str:
    """Return platform key used in manifest/asset names (e.g. darwin-arm64)."""
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


def _make_request(url: str, accept: str = "application/vnd.github.v3+json") -> Request:
    """Build a Request with optional GitHub auth from GITHUB_TOKEN env var."""
    headers = {"Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return Request(url, headers=headers)


def _is_update_check_due() -> bool:
    """Return True if enough time has passed since the last background update check."""
    try:
        if _LAST_CHECK_FILE.exists():
            last_check = float(_LAST_CHECK_FILE.read_text().strip())
            if time.time() - last_check < _UPDATE_CHECK_INTERVAL:
                return False
    except Exception:
        pass
    return True


def _record_update_check() -> None:
    """Write current timestamp to the last-check file."""
    try:
        _LAST_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_CHECK_FILE.write_text(str(time.time()))
    except Exception:
        pass


def _fetch_manifest(manifest_url: str | None) -> dict | None:
    """Fetch update manifest.

    Strategy (to avoid GitHub API rate limits):
    1. If DEVCTL_MANIFEST_URL is set, use that directly
    2. Otherwise, try the direct release asset URL (no rate limit)
    3. Fall back to GitHub Releases API only if direct URL fails
    """
    repo = os.environ.get("DEVCTL_GITHUB_REPO", "wi-devctl")
    owner = os.environ.get("DEVCTL_GITHUB_OWNER", "workindia")

    # 1. Explicit manifest URL from env var
    if manifest_url:
        try:
            with open_url(_make_request(manifest_url), timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            log_error(f"Failed to fetch manifest from {manifest_url}: {e}")
            return None

    # 2. Try direct release asset URL first (no rate limit)
    direct_url = f"https://github.com/{owner}/{repo}/releases/latest/download/manifest.json"
    try:
        with open_url(_make_request(direct_url), timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        pass  # Fall through to API

    # 3. Fallback: GitHub Releases API (has rate limits)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        with open_url(_make_request(api_url), timeout=10) as resp:
            data = json.loads(resp.read().decode())
        # Use the API asset URL (.url), not browser_download_url.
        # For private repos, browser_download_url redirects to a pre-signed CDN URL that
        # rejects the Authorization header. The API URL + Accept: application/octet-stream
        # lets GitHub handle auth cleanly before redirecting.
        assets = {a["name"]: a["url"] for a in data.get("assets", [])}
        tag = data.get("tag_name", "v0.0.0")
        downloads = {}
        for name, url in assets.items():
            if name.startswith("devctl-") and not name.endswith(".json"):
                key = name.replace("devctl-", "", 1).rsplit(".", 1)[0]
                downloads[key] = url
        return {"latest_version": tag, "downloads": downloads}
    except HTTPError as e:
        if e.code == 404:
            return None
        log_error(f"Failed to fetch GitHub release: {e}")
        return None
    except Exception as e:
        log_error(f"Failed to fetch GitHub release: {e}")
        return None


def check_for_update(manifest_url: str | None) -> Tuple[bool, str, str | None]:
    """Check if an update is available. Returns (has_update, latest_version, download_url)."""
    manifest = _fetch_manifest(manifest_url)
    if not manifest:
        return False, __version__, None

    latest = manifest.get("latest_version", "")
    downloads = manifest.get("downloads", {})
    platform_key = _get_platform_key()
    download_url = downloads.get(platform_key)

    if not download_url:
        return False, __version__, None

    def norm(v: str) -> str:
        return v.lstrip("v")

    if norm(latest) > norm(__version__):
        return True, latest, download_url
    return False, latest, download_url


def perform_update(manifest_url: str | None, force: bool = False) -> Tuple[bool, str, str | None]:
    """Check for an update and apply it when available.

    When an update is downloaded and installed, this function re-execs the new
    binary (os.execv) and never returns. Otherwise it returns
    (has_update, latest_version, download_url).

    Background checks are rate-limited to once per DEVCTL_UPDATE_CHECK_INTERVAL_HOURS
    (default 24 h). Pass force=True to bypass the rate limit (used by `devctl update-cli`).
    """
    if not force and not _is_update_check_due():
        return False, __version__, None

    _record_update_check()

    has_update, latest_version, download_url = check_for_update(manifest_url)

    if not has_update:
        # No update available - return early even if force=True
        # This prevents infinite loop when already on latest version
        return False, latest_version or __version__, download_url

    if not download_url:
        if force:
            log_error("No download URL available for this platform.")
        return False, latest_version or __version__, None

    try:
        req = _make_request(download_url, accept="application/octet-stream")
        with open_url(req, timeout=60) as resp:
            new_binary = resp.read()
    except Exception as e:
        log_error(f"Failed to download update: {e}")
        return False, latest_version, None

    if not getattr(sys, "frozen", False):
        log_error("Auto-update only works when running the installed binary.")
        return False, latest_version, None

    exe = sys.executable
    try:
        fd, path = tempfile.mkstemp(suffix=".devctl", prefix="devctl-")
        try:
            os.write(fd, new_binary)
            os.close(fd)
            os.chmod(path, 0o755)
            os.replace(path, exe)
        except Exception:
            os.close(fd)
            if os.path.exists(path):
                os.unlink(path)
            raise
    except Exception as e:
        log_error(f"Failed to replace binary: {e}")
        return False, latest_version, None

    os.execv(exe, [exe] + sys.argv[1:])
    return True, latest_version, download_url  # unreachable
