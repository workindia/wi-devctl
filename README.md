# devctl

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

Developer control plane CLI — sync and manage developer tooling configurations from any repo. Think of it as "paracetamol for developer setup": distribute configs from central repos and keep local environments in sync.

## Features

- **Protocol-driven sync** — Define what to sync in `protocol.yaml` (obligations + recommendations)
- **Repo-agnostic** — Works with any Git repo; no hardcoded URLs
- **Multiple domains** — ai-kit (Cursor rules, skills), devspace (planned), local (planned)
- **Self-updating binary** — Single executable with automatic updates from GitHub releases
- **Background config sync** — Optional hourly pull via launchd (macOS) or cron (Linux), with desktop notifications when updates land
- **One-shot install** — Optional `install.sh` env vars to install devctl, run `ai-kit setup`, and register background sync in one run
- **Backup before overwrite** — One run-level snapshot of protocol targets before applying; restores that snapshot if apply fails; old run backups are pruned (keeps last 3 runs per repo by default)

## High-Level Design (HLD)

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI Layer (cli/)                          │
│  main │ ai-kit │ devspace │ local │ list │ update-cli            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     Core Layer (core/)                           │
│  protocol_engine │ repo_manager │ versioning │ backup │ updater   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    Utils Layer (utils/)                           │
│  shell │ yaml_loader │ logging │ notify                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                   Local Storage (~/.devctl/)                     │
│  repos/ │ backups/ │ logs/ │ state.json │ .last_update_check       │
└─────────────────────────────────────────────────────────────────┘
```

| Layer | Module | Responsibility |
|-------|--------|----------------|
| **CLI** | main | Root group, auto-update hook, `list`, `update-cli` |
| **CLI** | ai-kit | setup, sync, update, install/uninstall-background-sync, status, doctor |
| **CLI** | devspace / local | Domain stubs (planned) |
| **Core** | repo_manager | Clone/pull Git repos, URL → slug |
| **Core** | protocol_engine | Parse `protocol.yaml`, execute `file_sync` / `symlink_sync`, etc. |
| **Core** | versioning | Persist repo metadata in `state.json` |
| **Core** | backup | One run-level snapshot before apply; restore on failure; prune old runs |
| **Core** | updater | Self-update binary from GitHub releases |
| **Core** | config_sync | Check managed repos for new pushes, pull and re-apply, notify |
| **Core** | background_sync | Install/uninstall launchd (macOS) or cron (Linux) for hourly sync |
| **Utils** | shell, yaml_loader, logging, notify | Paths, YAML, stderr logging, OS notifications |

### Data Flow (ai-kit setup)

```
User: devctl ai-kit setup --repo https://github.com/org/configs
         │
         ▼
  main.cli() ──► _maybe_auto_update() ──► ai_kit.setup()
         │                │                        │
         │                │                        ├──► repo_manager.clone_or_pull()
         │                │                        ├──► protocol_engine.apply_protocols()
│                │                        │         ├──► backup.backup_apply_run() (once)
│                │                        │         ├──► file_sync (merge copy)
         │                │                        │         └──► symlink_sync (shared skills/commands)
         │                │                        └──► versioning.register_repo()
         │                │
         │                └── check wi-devctl releases
         │
         │  (separate: launchd/cron runs devctl ai-kit sync hourly)
         │       └── config_sync: fetch → pull if behind → re-apply → notify
         │
         ▼
  Repo cloned → ~/.devctl/repos/org-configs/
  Configs merged → ~/.cursor (or target from protocol.yaml)
  State saved → ~/.devctl/state.json
```

## Installation

`install.sh` downloads a pre-built **devctl** binary from GitHub Releases. You need at least one release (a `v*` tag). Supported assets:

- `devctl-darwin-amd64`, `devctl-darwin-arm64`, `devctl-linux-amd64`

### Public repositories

```bash
curl -fsSL https://raw.githubusercontent.com/WorkIndia-Private/wi-devctl/main/install.sh | bash
```

### One-shot: binary + ai-kit + background sync

Set these **before** piping `install.sh` into `bash`. After the binary is installed, the script can run `ai-kit setup` and register hourly sync.

```bash
export DEVCTL_AI_KIT_REPO=https://github.com/your-org/your-ai-config-repo
export DEVCTL_AI_KIT_BACKGROUND_SYNC=1
curl -fsSL https://raw.githubusercontent.com/WorkIndia-Private/wi-devctl/main/install.sh | bash
```

| Variable | Effect |
|----------|--------|
| `DEVCTL_AI_KIT_REPO` | Run `devctl ai-kit setup --repo <url>` after install (**git** required on `PATH`) |
| `DEVCTL_AI_KIT_BACKGROUND_SYNC=1` | Then run `devctl ai-kit install-background-sync` (macOS / Linux only; skipped elsewhere) |

`GITHUB_TOKEN` used only for **curl** when fetching `install.sh` or release assets does **not** configure `git clone` for your config repo. Use SSH or a git credential helper for private repos.

Combine with a private **wi-devctl** install and one-shot ai-kit:

```bash
export GITHUB_TOKEN=ghp_xxx
export DEVCTL_AI_KIT_REPO=git@github.com:your-org/your-ai-config-repo.git
export DEVCTL_AI_KIT_BACKGROUND_SYNC=1
curl -fsSL \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/WorkIndia-Private/wi-devctl/contents/install.sh?ref=main" | bash
```

### Private wi-devctl (install script only)

If you only need the installer from a private repo (no one-shot ai-kit):

```bash
export GITHUB_TOKEN=ghp_xxx
curl -fsSL \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/WorkIndia-Private/wi-devctl/contents/install.sh?ref=main" | bash
```

## Usage

```bash
devctl ai-kit setup --repo <url>              # Clone / pull config repo, apply protocols
devctl ai-kit install-background-sync         # Hourly sync: launchd (macOS) or cron (Linux)
devctl ai-kit uninstall-background-sync       # Remove that scheduled job
devctl ai-kit sync                            # Run sync now; notifies when pulls happen
devctl ai-kit sync -v                         # Same, with step-by-step messages on stderr
devctl ai-kit update                          # Pull all managed repos and re-apply (explicit)
devctl ai-kit status                          # Show drift vs protocol obligations
devctl ai-kit doctor                          # Validate configs
devctl list                                   # List managed repos
devctl update-cli                             # Force devctl binary update
devctl --help
```

## Quick Start

1. Add a `protocol.yaml` to your config repo (see [examples/protocol.yaml](examples/protocol.yaml)):

```yaml
version: v1
protocols:
  - name: cursor
    type: file_sync
    source: .cursor
    target: ~/.cursor
    obligations: [rules/security.json]
  - name: cursor-skills
    type: symlink_sync
    source: .common/skills
    target: ~/.cursor/skills
```

2. Run setup:

```bash
devctl ai-kit setup --repo https://github.com/your-org/ai-configs
```

3. (Optional) Install background sync to auto-pull updates hourly and get notified:

```bash
devctl ai-kit install-background-sync
```

4. Repo is cloned to `~/.devctl/repos/`. Vendor config is merge-copied (`file_sync`); shared skills/commands are symlinked (`symlink_sync`).

## Protocol Reference

| Field | Description |
|-------|-------------|
| `type` | `file_sync` (merge copy) or `symlink_sync` (directory symlink to source) |
| `source` | Path in repo (relative to root) |
| `target` | Local path (`~` expanded) |
| `obligations` | Required files under target (reported if missing) |
| `recommendations` | Optional files (reported if missing) |

Declare `file_sync` entries before `symlink_sync` entries. `protocol.yaml` or `protocol.yml` must live at the **root** of the repo you sync from.

## Domains & Use Cases

A **domain** is a grouped set of CLI commands for a specific use case. Each domain reuses the same core (repo manager, protocol engine, versioning, backup) but adds domain-specific behavior.

| Domain | Purpose | Status |
|--------|---------|--------|
| **ai-kit** | Sync AI tooling configs (Cursor rules, skills) from repos | ✅ Implemented |
| **devspace** | Dev environment provisioning (containers, VMs) | 🚧 Planned |
| **local** | Local dev tooling (env vars, daemons, scripts) | 🚧 Planned |

### How use cases work

All domains share the same flow: clone repo → parse `protocol.yaml` → apply protocols → track state. The protocol engine supports `file_sync` and `symlink_sync` (extensible to `env_sync`, `script_run`, etc.). Domain-specific logic sits on top of this core.

| Use case | Domain | What it does | Example |
|----------|--------|---------------|---------|
| **AI configs** | ai-kit | Sync vendor config via `file_sync`; shared skills/commands via `symlink_sync` | Cursor rules, shared agent skills |
| **Dev environments** | devspace | Define containers/VMs, start Docker/Podman | Dev containers, Colima setup |
| **Local tooling** | local | Sync env vars, run setup scripts | `.env` files, dev daemons |
| **Security** | (new domain) | Scan for secrets, enforce policies | Pre-commit hooks, policy configs |

### Adding a new domain

1. Add `cli/my_domain.py` with a Click group and commands.
2. Register in `main.py`: `cli.add_command(my_domain, "my-domain")`.
3. Reuse `repo_manager`, `protocol_engine`, `versioning` from core.
4. Add new protocol types in `protocol_engine.execute_protocol()` if needed (e.g. `type: script_run`).

Fork the repo and add domains for your org — no hardcoded URLs; each domain works with any repo that includes a `protocol.yaml`.

## Configuration

| Variable | Description |
|----------|-------------|
| `DEVCTL_MANIFEST_URL` | Custom manifest URL for updates |
| `DEVCTL_SKIP_AUTO_UPDATE` | Set to `1` to disable auto-update |
| `DEVCTL_SKIP_NOTIFY` | Set to `1` to disable OS notifications on sync |
| `DEVCTL_VERBOSE` | Set to `1` or use `-v` for verbose output |
| `DEVCTL_GITHUB_OWNER` | GitHub org (default: WorkIndia-Private) |
| `DEVCTL_GITHUB_REPO` | Repo name (default: wi-devctl) |
| `DEVCTL_UPDATE_CHECK_INTERVAL_HOURS` | Hours between auto-update checks (default: 24) |
| `DEVCTL_CONFIG_SYNC_INTERVAL_MINUTES` | Minutes between ai-kit config sync rate-limit checks; overrides `DEVCTL_CONFIG_SYNC_INTERVAL_HOURS` when set (fractional ok) |
| `DEVCTL_CONFIG_SYNC_INTERVAL_HOURS` | Hours between config sync checks when minutes unset (default: 1; fractional ok) |
| `DEVCTL_BACKUP_RETENTION_COUNT` | Number of **run-level** config backups to keep per repo slug (default: 3). Set to `0` to disable pruning |
| `DEVCTL_BACKUP_RETENTION_DISABLED` | Set to `1` to keep all backups (no automatic pruning) |
| `DEVCTL_AI_KIT_REPO` | *(install.sh only)* If set, run `ai-kit setup` after binary install |
| `DEVCTL_AI_KIT_BACKGROUND_SYNC` | *(install.sh only)* Set to `1` to run `install-background-sync` after setup |

### Background sync and notifications

After `ai-kit setup`, install the scheduler so repos stay current without running `devctl` manually:

1. `devctl ai-kit install-background-sync`
2. **macOS**: `~/Library/LaunchAgents/com.devctl.config-sync.plist`, interval **3600** seconds  
   **Linux**: cron line at minute 0 each hour (`0 * * * * … ai-kit sync`)

The job runs `devctl ai-kit sync`. When new commits are pulled, devctl shows a **desktop notification** (macOS: AppleScript; Linux: `notify-send`). Set `DEVCTL_SKIP_NOTIFY=1` to turn notifications off.

**Logs:** stdout and stderr from the scheduled job are appended to:

`~/.devctl/logs/background-sync.log`

The file is created at install (empty until the first run). **macOS** does not run the job until the next interval (**3600 s**) unless you kickstart (below), so the log can stay empty until then.

```bash
tail -f ~/.devctl/logs/background-sync.log
```

If the log path in your plist/cron is wrong, run `devctl ai-kit uninstall-background-sync` and `install-background-sync` again.

**Common gotchas**

- **Do not install with `sudo`** — the plist and log path are tied to the user that ran install (`Path.home()`). If you used sudo, logs live under root’s home, not yours.
- **Buffered output** — scheduled runs use a non-TTY stdout; the job sets `PYTHONUNBUFFERED=1` so lines appear promptly after each run.

**Quick check (macOS)** after install — inspect launchd state (e.g. `state`, last exit status):

```bash
launchctl print "gui/$(id -u)/com.devctl.config-sync"
```

Force one run immediately:

```bash
launchctl kickstart -k "gui/$(id -u)/com.devctl.config-sync"
```

**Verbose manual sync:**

```bash
devctl ai-kit sync -v
```

Interactive `devctl ai-kit update` still works when you want explicit pulls and printed output per repo.

## Project Structure

```
wi-devctl/
├── src/devctl/
│   ├── cli/           # main, ai-kit, devspace, local
│   ├── core/          # protocol_engine, repo_manager, versioning, backup, updater, config_sync, background_sync
│   └── utils/         # shell, yaml_loader, logging, notify
├── examples/
│   └── protocol.yaml
├── tests/
├── install.sh
└── .github/workflows/release.yml
```

## Development

```bash
git clone https://github.com/WorkIndia-Private/wi-devctl.git
cd wi-devctl
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# Run tests
pytest

# Build binary locally
pyinstaller --onefile --name devctl --paths src \
  --hidden-import certifi --collect-all certifi \
  src/devctl/cli/main.py
./dist/devctl --help
```

### Automated tests

Run `pytest` from the repo root (uses `pythonpath = ["src"]` in `pyproject.toml`).

| Area | File | What it covers |
|------|------|----------------|
| **Protocols** | `tests/test_protocol_engine.py` | Load YAML/YML, validation errors, `file_sync`, `symlink_sync`, merge behavior, **obligations / recommendations** present vs missing, unknown type, missing source, `apply_protocols` across multiple protocols |
| **Updater** | `tests/test_updater.py` | Manifest / version comparison, platform key shape, `perform_update` rate limit and force paths (no real download) |
| **Config sync** | `tests/test_config_sync.py` | `perform_config_sync`: no repos, rate limit, pull + notify, skip bad path / no remote updates |
| **CLI** | `tests/test_cli.py` | `list`, `ai-kit sync`, `update-cli`, `--version`, `devspace`/`local` help (`DEVCTL_SKIP_AUTO_UPDATE=1`, isolated `HOME`) |
| **State** | `tests/test_versioning.py` | `state.json`, `register_repo`, `get_repo_version` |
| **Background install** | `tests/test_background_sync.py` | launchd plist write (mocked `launchctl`), missing binary, uninstall when absent |
| **Notifications** | `tests/test_notify.py` | `DEVCTL_SKIP_NOTIFY`, macOS `osascript` path |
| **Repos** | `tests/test_repo_manager.py` | URL → slug, `fetch_and_has_updates` (mocked git) |
| **Backups** | `tests/test_backup.py` | Run-level snapshots, restore, retention pruning, dry-run |
| **SSL** | `tests/test_ssl_certs.py` | certifi CA bundle configuration for HTTPS |

End-to-end **git clone**, **auto-update binary replace**, and **real launchd/cron** are not run in CI (use a manual machine or staging for those).

## Releasing

Merging a PR does **not** auto-tag. After your changes are on `main`, create a release tag using either method below. Pushing a `v*` tag triggers the **Release** workflow (builds binaries and publishes a GitHub Release).

### Option A: GitHub Actions (recommended)

1. Merge the PR to `main`
2. Go to **Actions → Create release tag → Run workflow**
3. Enter the version (e.g. `v0.4.1`)
4. The workflow tags `main`, pushes the tag, and explicitly triggers **Release** (GitHub does not auto-start workflows for tag pushes made with `GITHUB_TOKEN`)

### Option B: Command line

```bash
git checkout main && git pull
git tag v0.4.1
git push origin v0.4.1
```

Auto-update uses the GitHub Releases API (or `DEVCTL_MANIFEST_URL` if set).

## License

MIT
