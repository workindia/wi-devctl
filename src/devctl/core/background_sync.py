"""Install background sync (launchd on macOS, cron on Linux)."""

import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from devctl.utils.shell import get_background_sync_log_path, get_logs_dir

_LAUNCHD_LABEL = "com.devctl.config-sync"


def _get_devctl_path() -> str | None:
    """Return the devctl binary path for use in cron/launchd."""
    if getattr(sys, "frozen", False):
        return sys.executable
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.name == "devctl" and argv0.is_file() and os.access(argv0, os.X_OK):
        return str(argv0)
    path = shutil.which("devctl")
    if path:
        return path
    return None


def _launchd_gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchd_activate(plist_path: Path) -> str | None:
    """Register the LaunchAgent in the user's GUI domain (modern launchctl)."""
    domain = _launchd_gui_domain()
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        capture_output=True,
    )
    try:
        subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            check=True,
            capture_output=True,
        )
        return None
    except subprocess.CalledProcessError as e:
        err_bootstrap = (e.stderr or b"").decode() or (e.stdout or b"").decode()
        try:
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                check=True,
                capture_output=True,
            )
            return None
        except subprocess.CalledProcessError as e2:
            err_load = (e2.stderr or b"").decode() or (e2.stdout or b"").decode()
            return err_bootstrap or err_load or "launchctl bootstrap/load failed"


def _launchd_deactivate(plist_path: Path) -> None:
    domain = _launchd_gui_domain()
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        capture_output=True,
    )
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )


def _launchd_kickstart() -> None:
    """Run the job once now so the log file populates and failures surface immediately."""
    key = f"{_launchd_gui_domain()}/{_LAUNCHD_LABEL}"
    subprocess.run(
        ["launchctl", "kickstart", "-k", key],
        capture_output=True,
    )


def _install_launchd(devctl_path: str) -> str | None:
    """Install launchd plist for hourly sync. Returns error message or None."""
    home = Path.home()
    plist_dir = home / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{_LAUNCHD_LABEL}.plist"

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
  <string>{_LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{devctl_esc}</string>
    <string>ai-kit</string>
    <string>sync</string>
    <string>--background</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>RunAtLoad</key>
  <true/>
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
        err = _launchd_activate(plist_path)
        if err:
            return err
        _launchd_kickstart()
        return None
    except Exception as e:
        return str(e)


def _install_cron(devctl_path: str) -> str | None:
    """Add @hourly cron job. Returns error message or None."""
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    log_path = get_background_sync_log_path()
    log_path.touch(exist_ok=True)
    # env ensures line-oriented logs when stdout is not a TTY (fully buffered otherwise).
    cron_line = (
        f"0 * * * * env PYTHONUNBUFFERED=1 {devctl_path} ai-kit sync --background"
        f" >> {log_path} 2>&1\n"
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
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        if not plist_path.exists():
            return True, "Background sync was not installed."
        try:
            _launchd_deactivate(plist_path)
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


def describe_background_sync_status() -> str:
    """Human-readable background sync diagnostics (macOS launchd / Linux cron)."""
    system = platform.system().lower()
    if system == "darwin":
        return _describe_background_sync_darwin()
    if system == "linux":
        return _describe_background_sync_linux()
    return f"Background sync is only available on macOS and Linux (this OS reports: {system})."


def _describe_background_sync_darwin() -> str:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
    log_path = get_background_sync_log_path()
    lines: list[str] = []
    if not plist_path.exists():
        lines.append("Background sync: not installed (LaunchAgent plist missing).")
        lines.append("  Install: devctl ai-kit install-background-sync")
        return "\n".join(lines)

    lines.append("Background sync: LaunchAgent plist present")
    lines.append(f"  plist: {plist_path}")
    lines.append(f"  log:   {log_path}")

    domain = _launchd_gui_domain()
    key = f"{domain}/{_LAUNCHD_LABEL}"
    if log_path.exists():
        st = log_path.stat()
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"  log on disk: {st.st_size} bytes, last modified {mtime} (local time)")
        if st.st_size == 0:
            lines.append(
                "  Log is empty until the job runs. One-line summaries are written each run (since recent devctl)."
            )
            lines.append(f'  Force one run: launchctl kickstart -k "{key}"')
    else:
        lines.append("  log on disk: missing (reinstall: devctl ai-kit install-background-sync)")

    proc = subprocess.run(
        ["launchctl", "print", key],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        lines.append("  launchd: not registered in this session, or print failed.")
        if err:
            lines.append(f"  detail: {err[:400]}")
        lines.append(f"  Check: launchctl print {key}")
        lines.append(
            "  Reinstall: devctl ai-kit uninstall-background-sync && "
            "devctl ai-kit install-background-sync"
        )
        return "\n".join(lines)

    out = proc.stdout or ""
    state_m = re.search(r"^\s*state\s*=\s*(\S+)", out, re.MULTILINE | re.IGNORECASE)
    lines.append("  launchd: registered")
    if state_m:
        lines.append(f"  state: {state_m.group(1)}")
    pid_m = re.search(r"^\s*pid\s*=\s*(\S+)", out, re.MULTILINE | re.IGNORECASE)
    if pid_m and pid_m.group(1) not in ("0", "-"):
        lines.append(f"  pid: {pid_m.group(1)}")
    last_exit_m = re.search(
        r"last exit (?:status|code)\s*=\s*(\S+)",
        out,
        re.IGNORECASE,
    )
    if last_exit_m:
        lines.append(f"  last exit status: {last_exit_m.group(1)}")
    if not state_m:
        lines.append(f"  (full job: launchctl print {key})")
    return "\n".join(lines)


def _describe_background_sync_linux() -> str:
    log_path = get_background_sync_log_path()
    proc = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
    )
    lines: list[str] = []
    if proc.returncode != 0:
        lines.append("Background sync: no user crontab (or crontab -l failed).")
        lines.append(f"  log (if ever installed): {log_path}")
        return "\n".join(lines)
    tab = proc.stdout or ""
    hits = [ln.strip() for ln in tab.splitlines() if "devctl" in ln and "ai-kit sync" in ln]
    if not hits:
        lines.append("Background sync: not installed (no devctl ai-kit sync cron line).")
        lines.append("  Install: devctl ai-kit install-background-sync")
        return "\n".join(lines)
    lines.append("Background sync: cron entry present")
    for h in hits:
        lines.append(f"  {h}")
    lines.append(f"  log: {log_path}")
    if log_path.exists():
        st = log_path.stat()
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"  log on disk: {st.st_size} bytes, last modified {mtime} (local time)")
    return "\n".join(lines)
