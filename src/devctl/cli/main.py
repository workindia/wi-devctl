"""Root CLI - version, update-cli, list, command groups."""

import os

import click

from devctl import __version__
from devctl.cli.ai_kit import ai_kit
from devctl.cli.devspace import devspace
from devctl.cli.local import local
from devctl.core.versioning import list_repos


def _maybe_auto_update() -> None:
    """Check for update and apply silently if available. Skip if DEVCTL_SKIP_AUTO_UPDATE=1."""
    if os.environ.get("DEVCTL_SKIP_AUTO_UPDATE") == "1":
        return
    manifest_url = os.environ.get("DEVCTL_MANIFEST_URL")
    from devctl.core.updater import perform_update

    # perform_update re-execs on success; force=False so we only update when newer
    perform_update(manifest_url, force=False)


@click.group()
@click.version_option(version=__version__, prog_name="devctl")
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output (or DEVCTL_VERBOSE=1)")
def cli(verbose: bool) -> None:
    """Developer control plane - sync and manage developer tooling from any repo."""
    from devctl.utils.logging import set_verbose

    set_verbose(verbose or os.environ.get("DEVCTL_VERBOSE") == "1")
    _maybe_auto_update()


@cli.command("list")
def list_cmd() -> None:
    """List all managed repos."""
    repos = list_repos()
    if not repos:
        click.echo("No managed repos. Run 'devctl ai-kit setup --repo <url>' to add one.")
        return
    for slug, info in repos.items():
        click.echo(f"  {slug}: {info.get('url', '?')} (v{info.get('version', '?')})")


@cli.command()
@click.option("--manifest-url", envvar="DEVCTL_MANIFEST_URL", help="Manifest URL for update check")
def update_cli(manifest_url: str | None) -> None:
    """Force update the devctl CLI binary."""
    from devctl.core.updater import perform_update

    # perform_update re-execs on success, so we only return when no update or error
    has_update, latest_version, download_url = perform_update(manifest_url, force=True)
    if not has_update or not download_url:
        click.echo("Already up to date.")
    else:
        click.echo("Update failed. See stderr for details.", err=True)


cli.add_command(ai_kit, "ai-kit")
cli.add_command(devspace, "devspace")
cli.add_command(local, "local")

if __name__ == "__main__":
    cli()
