"""Logging utilities."""

import sys

VERBOSE = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose output."""
    global VERBOSE
    VERBOSE = enabled


def log_verbose(msg: str) -> None:
    """Log to stderr only when verbose mode is enabled."""
    if VERBOSE:
        print(f"devctl: {msg}", file=sys.stderr)


def log_error(msg: str) -> None:
    """Log error to stderr."""
    print(f"devctl: error: {msg}", file=sys.stderr)


def log_warn(msg: str) -> None:
    """Log warning to stderr."""
    print(f"devctl: warning: {msg}", file=sys.stderr)


def log_info(msg: str) -> None:
    """Log info to stderr (for non-interactive output)."""
    print(f"devctl: {msg}", file=sys.stderr)
