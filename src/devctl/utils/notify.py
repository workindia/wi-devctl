"""OS notifications for devctl."""

import os
import subprocess
import sys


def send_notification(title: str, body: str) -> None:
    """Send a desktop notification. No-op if unsupported or DEVCTL_SKIP_NOTIFY=1."""
    if os.environ.get("DEVCTL_SKIP_NOTIFY") == "1":
        return
    try:
        if sys.platform == "darwin":
            # Escape " for AppleScript string
            body_esc = body.replace("\\", "\\\\").replace('"', '\\"')
            title_esc = title.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{body_esc}" with title "{title_esc}"',
                ],
                capture_output=True,
                timeout=5,
            )
        elif sys.platform == "linux":
            subprocess.run(
                ["notify-send", title, body],
                capture_output=True,
                timeout=5,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
