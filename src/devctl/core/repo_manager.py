"""Repository management - clone and pull repos."""

import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from devctl.utils.logging import log_verbose
from devctl.utils.shell import get_repos_dir


def url_to_slug(repo_url: str) -> str:
    """Convert repo URL to slug. Supports both HTTP(S) and SSH URLs.

    Examples:
        https://github.com/org/repo.git -> org-repo
        git@github.com:org/repo.git -> org-repo
    """
    url = repo_url.strip()
    # SSH format: git@host:org/repo or git@host:org/repo.git
    if url.startswith("git@"):
        # Extract path after the colon (org/repo or org/repo.git)
        if ":" in url:
            path = url.split(":", 1)[1]
        else:
            path = url
    else:
        parsed = urlparse(url)
        path = parsed.path.strip("/")

    # Remove .git suffix
    if path.endswith(".git"):
        path = path[:-4]
    # Replace / with -
    slug = path.replace("/", "-")
    # Sanitize: only alphanumeric, dash, underscore
    slug = re.sub(r"[^\w\-]", "", slug)
    return slug or "repo"


def resolve_default_branch(repo_url: str) -> str:
    """Return remote default branch name (e.g. main)."""
    result = subprocess.run(
        ["git", "ls-remote", "--symref", repo_url, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            ref = line.split()[1]
            return ref.rsplit("/", 1)[-1]
    raise RuntimeError(f"Could not resolve default branch for {repo_url}")


def _checkout_and_pull(repo_path: Path, branch: str) -> None:
    """Fetch, checkout branch, and fast-forward pull."""
    subprocess.run(
        ["git", "fetch", "origin"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", branch],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def clone_or_pull(repo_url: str, branch: str | None = None) -> Path:
    """Clone repo or pull if exists. Returns path to repo root."""
    repos_dir = get_repos_dir()
    repos_dir.mkdir(parents=True, exist_ok=True)

    slug = url_to_slug(repo_url)
    repo_path = repos_dir / slug
    effective_branch = branch.strip() if branch and branch.strip() else None

    if repo_path.exists():
        if effective_branch:
            log_verbose(f"Pulling latest on {effective_branch}: {repo_url}")
            _checkout_and_pull(repo_path, effective_branch)
            log_verbose(f"Updated {repo_path} (branch {effective_branch})")
        else:
            log_verbose(f"Pulling latest: {repo_url}")
            subprocess.run(
                ["git", "pull"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            log_verbose(f"Pulled to {repo_path}")
    elif effective_branch:
        log_verbose(f"Cloning {repo_url} (branch {effective_branch}) -> {repo_path}")
        try:
            subprocess.run(
                ["git", "clone", "--branch", effective_branch, repo_url, str(repo_path)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            log_verbose(f"Clone --branch failed, falling back to checkout {effective_branch}")
            subprocess.run(
                ["git", "clone", repo_url, str(repo_path)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", effective_branch],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
        log_verbose(f"Cloned to {repo_path}")
    else:
        log_verbose(f"Cloning {repo_url} -> {repo_path}")
        subprocess.run(
            ["git", "clone", repo_url, str(repo_path)],
            check=True,
            capture_output=True,
        )
        log_verbose(f"Cloned to {repo_path}")

    return repo_path


def fetch_and_has_updates(repo_path: Path) -> bool:
    """Fetch from origin and return True if remote has new commits (local is behind)."""
    log_verbose(f"git fetch origin (cwd={repo_path})")
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        err = getattr(e, "stderr", None) or b""
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        log_verbose(f"git fetch failed: {err or e}")
        return False
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if branch_result.returncode != 0 or not branch_result.stdout.strip():
        log_verbose("could not resolve current branch")
        return False
    branch = branch_result.stdout.strip()
    remote_ref = f"origin/{branch}"
    result = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..{remote_ref}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_verbose(f"no upstream commits vs {remote_ref} (missing ref or diverged)")
        return False
    try:
        behind = int(result.stdout.strip())
    except (ValueError, AttributeError):
        return False
    log_verbose(f"branch {branch}: {behind} commit(s) behind {remote_ref}")
    return behind > 0


def get_repo_path(repo_url: str | None = None, slug: str | None = None) -> Path | None:
    """Get path to repo by URL or slug. Returns None if not found."""
    repos_dir = get_repos_dir()
    if not repos_dir.exists():
        return None

    if slug:
        path = repos_dir / slug
        return path if path.exists() else None

    if repo_url:
        s = url_to_slug(repo_url)
        path = repos_dir / s
        return path if path.exists() else None

    return None
