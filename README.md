# devctl

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

Developer control plane CLI — sync and manage developer tooling configurations from any repo. Think of it as "paracetamol for developer setup": distribute configs from central repos and keep local environments in sync.

## Features

- **Protocol-driven sync** — Define what to sync in `protocol.yaml` (obligations + recommendations)
- **Repo-agnostic** — Works with any Git repo; no hardcoded URLs
- **Multiple domains** — ai-kit (Cursor rules, skills), devspace (planned), local (planned)
- **Self-updating binary** — Single executable with automatic updates from GitHub releases
- **Backup before overwrite** — Snapshots targets before applying changes

## Installation

### Public repositories

```bash
curl -fsSL https://raw.githubusercontent.com/WorkIndia-Private/wi-devctl/main/install.sh | bash
```

### Private repositories

Export a GitHub token with `repo` scope, then:

```bash
export GITHUB_TOKEN=ghp_xxx
curl -fsSL \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/WorkIndia-Private/wi-devctl/contents/install.sh?ref=main" | bash
```

Requires at least one release (push a `v*` tag). Binaries are built for:
- `darwin-amd64` (macOS Intel)
- `darwin-arm64` (macOS Apple Silicon)
- `linux-amd64`

## Usage

```bash
devctl ai-kit setup --repo <repo_url>   # Clone repo, apply protocols
devctl ai-kit update                    # Pull latest and re-apply
devctl ai-kit status                    # Show drift
devctl ai-kit doctor                    # Validate configs
devctl list                             # List managed repos
devctl update-cli                       # Force CLI update
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
    recommendations: [skills/debugging.md]
```

2. Run setup:

```bash
devctl ai-kit setup --repo https://github.com/your-org/ai-configs
```

3. Repo is cloned to `~/.devctl/repos/`, configs are merged into `~/.cursor`.

## Protocol Reference

| Field | Description |
|-------|-------------|
| `source` | Path in repo (relative to root) |
| `target` | Local path (`~` expanded) |
| `obligations` | Required files under target (reported if missing) |
| `recommendations` | Optional files (reported if missing) |

`protocol.yaml` or `protocol.yml` must live at the **root** of the repo you sync from.

## Domains & Use Cases

A **domain** is a grouped set of CLI commands for a specific use case. Each domain reuses the same core (repo manager, protocol engine, versioning, backup) but adds domain-specific behavior.

| Domain | Purpose | Status |
|--------|---------|--------|
| **ai-kit** | Sync AI tooling configs (Cursor rules, skills) from repos | ✅ Implemented |
| **devspace** | Dev environment provisioning (containers, VMs) | 🚧 Planned |
| **local** | Local dev tooling (env vars, daemons, scripts) | 🚧 Planned |

### How use cases work

All domains share the same flow: clone repo → parse `protocol.yaml` → apply protocols → track state. The protocol engine supports multiple types (currently `file_sync`; extensible to `env_sync`, `script_run`, etc.). Domain-specific logic sits on top of this core.

| Use case | Domain | What it does | Example |
|----------|--------|---------------|---------|
| **AI configs** | ai-kit | Sync `.cursor` rules/skills to `~/.cursor` | Cursor rules, agent skills |
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
| `DEVCTL_VERBOSE` | Set to `1` or use `-v` for verbose output |
| `DEVCTL_GITHUB_OWNER` | GitHub org (default: WorkIndia-Private) |
| `DEVCTL_GITHUB_REPO` | Repo name (default: wi-devctl) |
| `DEVCTL_UPDATE_CHECK_INTERVAL_HOURS` | Hours between auto-update checks (default: 24) |

## Project Structure

```
wi-devctl/
├── src/devctl/
│   ├── cli/           # main, ai-kit, devspace, local
│   ├── core/          # protocol_engine, repo_manager, versioning, backup, updater
│   └── utils/         # shell, yaml_loader, logging
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
pyinstaller --onefile --name devctl --paths src src/devctl/cli/main.py
./dist/devctl --help
```

## Releasing

Push a tag to trigger the release workflow:

```bash
git tag v1.0.0
git push origin v1.0.0
```

CI builds binaries and creates a GitHub Release. Auto-update uses the GitHub Releases API (or `DEVCTL_MANIFEST_URL` if set).

## License

MIT
