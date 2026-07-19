"""ai-kit commands: setup, update, status, doctor."""

import sys
from pathlib import Path

import click

from devctl.core.protocol_engine import apply_protocols, load_protocols
from devctl.core.repo_manager import clone_or_pull, get_repo_path, url_to_slug
from devctl.core.versioning import list_repos, register_repo
from devctl.utils.logging import log_verbose
from devctl.utils.shell import expand_path


def _repo_label(slug: str, info: dict) -> str:
    """Format repo slug with optional branch for logs."""
    branch = info.get("branch")
    if branch:
        return f"{slug}@{branch}"
    return slug


def _repo_labels(repos: dict, slugs: list[str] | None = None) -> str:
    """Comma-separated repo labels, optionally filtered to slugs."""
    labels: list[str] = []
    for slug, info in repos.items():
        if slugs is not None and slug not in slugs:
            continue
        labels.append(_repo_label(slug, info))
    return ", ".join(labels)


@click.group()
def ai_kit() -> None:
    """AI kit - sync AI tooling configs from repos."""
    pass


@ai_kit.command()
@click.option("--repo", "repo_url", required=True, help="Repository URL to clone")
@click.option("--branch", default=None, help="Git branch to track (default: repo default branch)")
def setup(repo_url: str, branch: str | None) -> None:
    """Clone repo and apply protocols."""
    try:
        effective_branch = branch.strip() if branch and branch.strip() else None
        log_verbose(f"Setting up repo: {repo_url}")
        repo_path = clone_or_pull(repo_url, branch=effective_branch)
        slug = url_to_slug(repo_url)
        log_verbose(f"Applying protocols from {repo_path}")
        version, _, missing_obl, missing_rec = apply_protocols(repo_path, slug, do_backup=True)
        log_verbose(f"Registering {slug} in state")
        register_repo(slug, repo_url, repo_path, version, branch=effective_branch)
        if effective_branch:
            click.echo(f"Setup complete: {slug} (v{version}, branch {effective_branch})")
        else:
            click.echo(f"Setup complete: {slug} (v{version})")
        click.echo("Tip: run 'devctl ai-kit install-background-sync' to auto-pull updates hourly and get notified.")
        if missing_obl:
            click.echo("Missing obligations:", err=True)
            for p in missing_obl:
                click.echo(f"  - {p}", err=True)
        if missing_rec:
            click.echo("Recommendations (optional):", err=True)
            for p in missing_rec:
                click.echo(f"  - {p}", err=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@ai_kit.command()
@click.option("-v", "--verbose", is_flag=True, help="Show sync steps on stderr")
@click.option("--background", is_flag=True, hidden=True, help="Run silently for cron/launchd")
def sync(background: bool, verbose: bool) -> None:
    """Sync config repos (for cron/launchd). Auto-pulls latest and notifies when updates exist."""
    import os

    from devctl.core.config_sync import perform_config_sync
    from devctl.utils.logging import set_verbose

    if verbose or os.environ.get("DEVCTL_VERBOSE") == "1":
        set_verbose(True)

    updated = perform_config_sync(force=True, notify=True)
    if background:
        # launchd/cron attach stdout to background-sync.log — always emit one line so the log is verifiable.
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        repos = list_repos()
        if not repos:
            click.echo(f"[{ts}] devctl ai-kit sync: no managed repos")
        elif updated:
            labels = _repo_labels(repos, updated)
            click.echo(
                f"[{ts}] devctl ai-kit sync: updated {len(updated)} repo(s): {labels}"
            )
        else:
            labels = _repo_labels(repos)
            suffix = f" ({labels})" if labels else ""
            click.echo(f"[{ts}] devctl ai-kit sync: ok, {len(repos)} repo(s) up to date{suffix}")
    else:
        if not list_repos():
            click.echo("No managed repos. Run 'devctl ai-kit setup --repo <url>' first.")
        elif not updated:
            click.echo("Sync complete: all repos up to date.")
        else:
            for slug in updated:
                click.echo(f"Synced: {slug}")
    sys.stdout.flush()


@ai_kit.command("install-background-sync")
def install_background_sync_cmd() -> None:
    """Install hourly background sync (launchd on macOS, cron on Linux). Notifies when updates are pulled."""
    from devctl.core.background_sync import install_background_sync

    ok, msg = install_background_sync()
    if ok:
        click.echo(msg)
        click.echo("Check registration: devctl ai-kit background-sync-status")
    else:
        click.echo(f"Failed: {msg}", err=True)
        raise SystemExit(1)


@ai_kit.command("uninstall-background-sync")
def uninstall_background_sync_cmd() -> None:
    """Remove background sync (launchd/cron)."""
    from devctl.core.background_sync import uninstall_background_sync

    ok, msg = uninstall_background_sync()
    if ok:
        click.echo(msg)
    else:
        click.echo(f"Failed: {msg}", err=True)
        raise SystemExit(1)


@ai_kit.command("background-sync-status")
def background_sync_status_cmd() -> None:
    """Show whether background sync is installed and launchd/cron registration."""
    from devctl.core.background_sync import describe_background_sync_status

    click.echo(describe_background_sync_status())


@ai_kit.command()
@click.option("--repo", "repo_url", help="Specific repo to update (default: all)")
def update(repo_url: str | None) -> None:
    """Pull latest and re-apply protocols."""
    repos = list_repos()
    if not repos:
        click.echo("No managed repos. Run 'devctl ai-kit setup --repo <url>' first.")
        return

    to_update = {}
    if repo_url:
        slug = url_to_slug(repo_url)
        if slug in repos:
            to_update[slug] = repos[slug]
        else:
            path = get_repo_path(repo_url=repo_url)
            if path:
                to_update[slug] = {"url": repo_url, "path": str(path)}
            else:
                click.echo(f"Repo not found: {repo_url}", err=True)
                raise SystemExit(1)
    else:
        to_update = repos

    for slug, info in to_update.items():
        try:
            url = info.get("url")
            path_str = info.get("path")
            if not url or not path_str:
                click.echo(f"Skipping {slug}: missing url or path", err=True)
                continue
            log_verbose(f"Updating {slug}: {url}")
            tracked_branch = info.get("branch")
            repo_path = clone_or_pull(url, branch=tracked_branch)
            log_verbose(f"Re-applying protocols for {slug}")
            version, _, missing_obl, missing_rec = apply_protocols(repo_path, slug, do_backup=True)
            register_repo(slug, url, repo_path, version, branch=tracked_branch)
            click.echo(f"Updated {slug} (v{version})")
            if missing_obl:
                click.echo(f"  Missing obligations: {len(missing_obl)}", err=True)
        except Exception as e:
            click.echo(f"Error updating {slug}: {e}", err=True)
            raise SystemExit(1)


@ai_kit.command("prune-backups")
@click.option("--dry-run", is_flag=True, help="Show backups that would be deleted without removing them")
def prune_backups_cmd(dry_run: bool) -> None:
    """Remove old config backups beyond the retention limit."""
    from devctl.core.backup import prune_backups

    deleted = prune_backups(dry_run=dry_run)
    if not deleted:
        click.echo("No backups to prune.")
        return

    action = "Would delete" if dry_run else "Deleted"
    click.echo(f"{action} {len(deleted)} backup(s):")
    for path in deleted:
        click.echo(f"  - {path}")


@ai_kit.command()
@click.option("--repo", "repo_url", help="Specific repo to check (default: all)")
def status(repo_url: str | None) -> None:
    """Show repo status and drift."""
    repos = list_repos()
    if not repos:
        click.echo("No managed repos.")
        return

    to_show = {}
    if repo_url:
        slug = url_to_slug(repo_url)
        if slug in repos:
            to_show[slug] = repos[slug]
        else:
            click.echo(f"Repo not found: {repo_url}", err=True)
            raise SystemExit(1)
    else:
        to_show = repos

    for slug, info in to_show.items():
        path = Path(info.get("path", ""))
        version = info.get("version", "?")
        click.echo(f"{slug}:")
        click.echo(f"  path:   {path}")
        click.echo(f"  version: {version}")
        if info.get("branch"):
            click.echo(f"  branch: {info['branch']}")
        if path.exists():
            try:
                log_verbose(f"Loading protocols from {path}")
                _, protocols = load_protocols(path)
                for p in protocols:
                    target = expand_path(p.target)
                    missing_obl = [target / r for r in p.obligations if not (target / r).exists()]
                    missing_rec = [target / r for r in p.recommendations if not (target / r).exists()]
                    if missing_obl or missing_rec:
                        click.echo(f"  protocol {p.name}:")
                        if missing_obl:
                            click.echo(f"    drift (obligations): {[str(x) for x in missing_obl]}")
                        if missing_rec:
                            click.echo(f"    recommendations: {[str(x) for x in missing_rec]}")
            except Exception as e:
                click.echo(f"  error: {e}", err=True)
        else:
            click.echo("  (path missing)")


@ai_kit.command()
@click.option("--repo", "repo_url", help="Specific repo to validate (default: all)")
def doctor(repo_url: str | None) -> None:
    """Validate configs and suggest fixes."""
    repos = list_repos()
    if not repos:
        click.echo("No managed repos.")
        return

    to_check = {}
    if repo_url:
        slug = url_to_slug(repo_url)
        if slug in repos:
            to_check[slug] = repos[slug]
        else:
            click.echo(f"Repo not found: {repo_url}", err=True)
            raise SystemExit(1)
    else:
        to_check = repos

    issues = 0
    for slug, info in to_check.items():
        path = Path(info.get("path", ""))
        if not path.exists():
            click.echo(f"{slug}: path missing - run 'devctl ai-kit setup --repo {info.get('url', '?')}'")
            issues += 1
            continue

        try:
            log_verbose(f"Validating {slug}")
            _, protocols = load_protocols(path)
            for p in protocols:
                target = expand_path(p.target)
                for r in p.obligations:
                    full = target / r
                    if not full.exists():
                        click.echo(f"{slug}: missing obligation {full}")
                        click.echo(f"  Fix: ensure {path / p.source / r} exists and run 'devctl ai-kit update --repo {info.get('url', '?')}'")
                        issues += 1
                for r in p.recommendations:
                    full = target / r
                    if not full.exists():
                        click.echo(f"{slug}: recommendation {full} (optional)")
        except FileNotFoundError:
            click.echo(f"{slug}: protocol.yaml or protocol.yml not found")
            issues += 1
        except Exception as e:
            click.echo(f"{slug}: {e}", err=True)
            issues += 1

    if issues == 0:
        click.echo("All configs valid.")
