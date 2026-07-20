"""Logging utilities."""

import os
import sys

VERBOSE = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose output."""
    global VERBOSE
    VERBOSE = enabled


def log_verbose(msg: str) -> None:
    """Log to stderr only when verbose mode is enabled."""
    if VERBOSE:
        print(f"devctl: {msg}", file=sys.stderr, flush=True)


def log_error(msg: str) -> None:
    """Log error to stderr."""
    print(f"devctl: error: {msg}", file=sys.stderr, flush=True)


def log_warn(msg: str) -> None:
    """Log warning to stderr."""
    print(f"devctl: warning: {msg}", file=sys.stderr, flush=True)


def log_info(msg: str) -> None:
    """Log info to stderr (for non-interactive output)."""
    print(f"devctl: {msg}", file=sys.stderr, flush=True)


def log_status(msg: str) -> None:
    """Log progress/status to stderr (always shown, for long-running operations)."""
    print(f"  → {msg}", file=sys.stderr, flush=True)


def _is_interactive() -> bool:
    """Check if stderr is connected to a terminal (interactive mode)."""
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


class ProgressBar:
    """Simple text-based progress bar for long-running operations."""

    def __init__(self, total: int, desc: str = "", width: int = 30) -> None:
        self.total = total
        self.current = 0
        self.desc = desc
        self.width = width
        self._interactive = _is_interactive()
        self._last_percent = -1

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes as human-readable size."""
        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def update(self, amount: int) -> None:
        """Update progress by the given amount."""
        self.current += amount
        percent = min(100, int(100 * self.current / self.total)) if self.total > 0 else 100

        if not self._interactive:
            # Non-interactive: only print at 0%, 25%, 50%, 75%, 100%
            if percent in (0, 25, 50, 75, 100) and percent != self._last_percent:
                self._last_percent = percent
                print(f"    {percent}% ({self._format_size(self.current)} / {self._format_size(self.total)})", file=sys.stderr, flush=True)
            return

        # Interactive: draw progress bar
        filled = int(self.width * self.current / self.total) if self.total > 0 else self.width
        bar = "█" * filled + "░" * (self.width - filled)
        current_str = self._format_size(self.current)
        total_str = self._format_size(self.total)
        line = f"\r    [{bar}] {percent:3d}% ({current_str} / {total_str})"
        print(line, end="", file=sys.stderr, flush=True)

    def finish(self) -> None:
        """Complete the progress bar and move to next line."""
        if self._interactive:
            # Clear the progress bar line
            print("\r" + " " * 80 + "\r", end="", file=sys.stderr, flush=True)
