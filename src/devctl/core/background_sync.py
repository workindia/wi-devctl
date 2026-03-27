"""Install background sync (launchd on macOS, cron on Linux)."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from devctl.utils.shell import get_background_sync_log_path, get_logs_dir


def _get_devctl_path() -> str | None:
    """Return the devctl binary path for use in cron/launchd."""
    if getattr(sys, "frozen", False):
        return sys.executable
    path = shutil.which("devctl")
    if path:
        return path
    # Fallback: current python + -m devctl (less reliable for cron)
    return None


def _install_launchd(devctl_path: str) -> str | None:
    """Install launchd plist for hourly sync. Returns error message or None."""
    home = Path.home()
    plist_dir = home / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.devctl.config-sync.plist"

    get_logs_dir().mkdir(parents=True, exist_ok=True)
    log_path = get_background_sync_log_path()
    log_path.touch(exist_ok=True)
    log_str = str(log_path)

    # escape plist string values (XML entity for & in paths)
    devctl_esc = devctl_path.replace("&", "&amp;").replace("\\", "\\\\").replace('"', '\\"')
    log_esc = log_str.replace("&", "&amp;")

    plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.devctl.config-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>{devctl_esc}</string>
    <string>ai-kit</string>
    <string>sync</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>RunAtLoad</key>
  <false/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>StandardOutPath</key>
  <string>{log_esc}</string>
  <key>StandardErrorPath</key>
  <string>{log_esc}</string>
</dict>
</plist>
'''
    try:
        plist_path.write_text(plist_content)
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            check=True,
            capture_output=True,
        )
        return None
    except subprocess.CalledProcessError as e:
        return str(e.stderr or e)
    except Exception as e:
        return str(e)


def _install_cron(devctl_path: str) -> str | None:
    """Add @hourly cron job. Returns error message or None."""
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    log_path = get_background_sync_log_path()
    log_path.touch(exist_ok=True)
    # env ensures line-oriented logs when stdout is not a TTY (fully buffered otherwise).
    cron_line = (
        f"0 * * * * env PYTHONUNBUFFERED=1 {devctl_path} ai-kit sync >> {log_path} 2>&1\n"
    )
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        existing = result.stdout or "" if result.returncode == 0 else ""
        if "devctl" in existing and "ai-kit sync" in existing:
            return None  # already installed
        new_crontab = existing.rstrip() + "\n" + cron_line if existing.strip() else cron_line
        proc = subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return proc.stderr or "crontab failed"
        return None
    except Exception as e:
        return str(e)


def install_background_sync() -> tuple[bool, str]:
    """Install background sync. Returns (success, message)."""
    devctl_path = _get_devctl_path()
    if not devctl_path:
        return False, "Could not find devctl binary. Install devctl first."

    system = platform.system().lower()
    if system == "darwin":
        err = _install_launchd(devctl_path)
        if err:
            return False, f"launchd install failed: {err}"
        log_file = get_background_sync_log_path()
        return True, f"Background sync installed (launchd, every hour). Logs: {log_file}"
    if system == "linux":
        err = _install_cron(devctl_path)
        if err:
            return False, f"cron install failed: {err}"
        log_file = get_background_sync_log_path()
        return True, f"Background sync installed (cron @hourly). Logs: {log_file}"
    return False, f"Background sync not supported on {system}."


def uninstall_background_sync() -> tuple[bool, str]:
    """Remove background sync. Returns (success, message)."""
    system = platform.system().lower()
    if system == "darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.devctl.config-sync.plist"
        if not plist_path.exists():
            return True, "Background sync was not installed."
        try:
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            plist_path.unlink()
            return True, "Background sync removed."
        except Exception as e:
            return False, str(e)
    if system == "linux":
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
            )
            existing = result.stdout or "" if result.returncode == 0 else ""
            if "devctl" not in existing or "ai-kit sync" not in existing:
                return True, "Background sync was not installed."
            lines = [
                ln for ln in existing.splitlines()
                if not ("devctl" in ln and "ai-kit sync" in ln)
            ]
            new_crontab = "\n".join(lines) + ("\n" if lines else "")
            subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
            return True, "Background sync removed."
        except Exception as e:
            return False, str(e)
    return False, f"Uninstall not supported on {system}."
