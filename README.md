# devctl

Developer control plane CLI - sync and manage developer tooling configurations from any repo.

## Purpose

**wi-devctl** is an internal developer platform CLI that:

- Syncs configs from **any repo** (no hardcoded URLs) via a protocol-driven model
- Enforces mandatory configs (obligations) and optional ones (recommendations)
- Supports multiple domains (ai-kit, devspace, local) and is extensible to security, etc.
- Distributes as a single binary with self-update
- Acts as a central control plane for developer tooling

**TL;DR:** "Paracetamol for developer setup" — removes local environment headaches by distributing configs from central repos.

---

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
│  protocol_engine │ repo_manager │ versioning │ backup │ updater  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    Utils Layer (utils/)                          │
│  shell │ yaml_loader │ logging                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                   Local Storage (~/.devctl/)                      │
│  repos/ │ backups/ │ state.json                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Data flow (ai-kit setup example)

```
User: devctl ai-kit setup --repo https://github.com/org/configs
         │
         ▼
  main.cli() ──► _maybe_auto_update() ──► ai_kit.setup()
         │                                        │
         │                                        ├──► repo_manager.clone_or_pull()
         │                                        ├──► protocol_engine.apply_protocols()
         │                                        │         ├──► backup.backup_target()
         │                                        │         └──► file_sync (merge copy)
         │                                        └──► versioning.register_repo()
         │
         ▼
  Repo cloned → ~/.devctl/repos/org-configs/
  Configs merged → ~/.cursor/ (or target from protocol.yaml)
  State saved → ~/.devctl/state.json
```

### Project structure

```
wi-devctl/
├── src/devctl/
│   ├── cli/           # Domains & root commands
│   │   ├── main.py    # Root group, list, update-cli
│   │   ├── ai_kit.py  # ai-kit domain
│   │   ├── devspace.py
│   │   └── local.py
│   ├── core/          # Reusable capabilities (domain-agnostic)
│   │   ├── protocol_engine.py
│   │   ├── repo_manager.py
│   │   ├── versioning.py
│   │   ├── backup.py
│   │   └── updater.py
│   └── utils/
│       ├── shell.py
│       ├── yaml_loader.py
│       └── logging.py
├── install.sh
├── examples/
└── .github/workflows/
```

---

## Core Capabilities (Reusable by All Domains)

These live in `core/` and are **domain-agnostic**. Any domain (ai-kit, devspace, local) can import and use them.

| Module | Responsibility | Key APIs | Used by |
|--------|----------------|----------|---------|
| **repo_manager** | Clone/pull Git repos, derive slug from URL | `clone_or_pull()`, `url_to_slug()`, `get_repo_path()` | ai-kit, devspace (future) |
| **protocol_engine** | Parse `protocol.yaml`, execute protocols | `load_protocols()`, `apply_protocols()`, `execute_protocol()` | ai-kit, devspace (future) |
| **versioning** | Persist repo metadata in `state.json` | `register_repo()`, `list_repos()`, `get_repo_version()` | ai-kit, main (list), devspace |
| **backup** | Snapshot target before overwrite | `backup_target()` | protocol_engine |
| **updater** | Self-update CLI binary from manifest | `check_for_update()`, `perform_update()` | main |

### What each core module does

- **repo_manager** — Clones a repo into `~/.devctl/repos/<slug>/` or pulls if already present. Converts `https://github.com/org/repo` → slug `org-repo`. Supports HTTP and SSH URLs.
- **protocol_engine** — Loads `protocol.yaml`/`protocol.yml` from repo root, validates it, and runs each protocol. Currently supports `file_sync` (merge copy). Extensible for `env_sync`, `script_run`, etc.
- **versioning** — Reads/writes `~/.devctl/state.json`. Tracks which repos are managed, their URLs, paths, versions, last-updated. `list_repos()` is shared; `devctl list` uses it.
- **backup** — Before overwriting a target (e.g. `~/.cursor`), copies it to `~/.devctl/backups/<slug>-<timestamp>/`. Enables rollback.
- **updater** — Fetches manifest (GitHub API or custom URL), compares version, downloads binary, atomically replaces self, re-execs. Only works when running the PyInstaller binary.

---

## What is a Domain?

A **domain** is a grouped set of CLI commands for a specific use case. It is a thin wrapper over core.

| Domain | Purpose | Status |
|--------|---------|--------|
| **ai-kit** | Sync AI tooling configs (Cursor rules, skills) from repos | Implemented |
| **devspace** | Dev environment provisioning (containers, VMs) | Stub |
| **local** | Local dev tooling (env vars, daemons) | Stub |

**Domain = Click group + commands that call core.** Domains do not implement clone/sync logic themselves; they delegate to `repo_manager`, `protocol_engine`, etc. They add domain-specific behavior (e.g. devspace might start Docker after applying protocols).

---

## Single Responsibility Principle (SRP)

Each module has one reason to change:

| Layer | Module | Single responsibility |
|-------|--------|------------------------|
| **utils** | `shell` | Path expansion (`~`), devctl dir paths |
| **utils** | `yaml_loader` | Load and parse YAML |
| **utils** | `logging` | Verbose/error output to stderr |
| **core** | `repo_manager` | Git clone/pull and path resolution |
| **core** | `protocol_engine` | Parse protocols, execute sync/copy |
| **core** | `backup` | Snapshot before overwrite |
| **core** | `versioning` | Persist and read repo state |
| **core** | `updater` | CLI self-update |
| **cli** | `main` | Root commands, auto-update hook, domain registration |
| **cli** | `ai_kit` | ai-kit UX (setup, update, status, doctor) |
| **cli** | `devspace` / `local` | Future domain UX |

**SRP in practice:**

- `repo_manager` does not parse YAML or write state — that’s `protocol_engine` and `versioning`.
- `protocol_engine` does not clone repos — that’s `repo_manager`.
- `backup` only creates snapshots; it does not decide when to backup — `protocol_engine` does.
- Domains orchestrate; core executes. Change in one area (e.g. new protocol type) is localized.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/wi-devctl/main/install.sh | bash
```

Set `DEVCTL_GITHUB_OWNER` and `DEVCTL_GITHUB_REPO` if using a different repo.

## Releasing to GitHub (for maintainers)

To publish devctl so anyone can install and use auto-update:

### 1. Prepare the repo

- Ensure `.github/workflows/release.yml` exists (builds binaries on tag push).
- Ensure `install.sh` is in the repo root.
- In `install.sh`, set `GITHUB_OWNER` and `GITHUB_REPO` defaults to your org/repo (replace `YOUR_ORG`).

### 2. Create a release

Push a tag that matches `v*` (e.g. `v1.0.0`):

```bash
git tag v1.0.0
git push origin v1.0.0
```

This triggers the release workflow:

1. **Build** — Matrix build on ubuntu, macos, windows; PyInstaller produces `devctl-{platform}` binaries.
2. **Release** — Creates a GitHub Release with tag `v1.0.0`, uploads:
   - `devctl-darwin-amd64`
   - `devctl-darwin-arm64`
   - `devctl-linux-amd64`
   - `devctl-windows-amd64.exe`
   - `manifest.json`

### 3. Manifest for auto-update

The workflow generates `manifest.json` and uploads it as a release asset. Its URLs point to the release assets (e.g. `https://github.com/OWNER/wi-devctl/releases/download/v1.0.0/devctl-darwin-arm64`).

The CLI uses this for auto-update in two ways:

- **GitHub API** (default): No `DEVCTL_MANIFEST_URL` → fetches `https://api.github.com/repos/{owner}/{repo}/releases/latest` and derives manifest from the release. Users must set `DEVCTL_GITHUB_OWNER` and `DEVCTL_GITHUB_REPO` (or you bake them into the binary).
- **Custom manifest**: Set `DEVCTL_MANIFEST_URL` to the raw URL of `manifest.json`, e.g.:
  ```
  https://github.com/OWNER/wi-devctl/releases/download/v1.0.0/manifest.json
  ```
  For “always latest”, host a redirect or a separate URL that serves the current manifest (GitHub doesn’t provide that directly).

### 4. Let users install

**Option A — Install script (recommended)**

Users run:

```bash
GITHUB_OWNER=YOUR_ORG GITHUB_REPO=wi-devctl \
  curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/wi-devctl/main/install.sh | bash
```

Or host `install.sh` on your own domain and set `GITHUB_OWNER` / `GITHUB_REPO` in the script.

**Option B — Direct download**

```bash
# Example for macOS Apple Silicon
curl -fsSL -o devctl https://github.com/YOUR_ORG/wi-devctl/releases/latest/download/devctl-darwin-arm64
chmod +x devctl
sudo mv devctl /usr/local/bin/
```

### 5. Auto-update configuration

For installed binaries to self-update, one of:

- **GitHub API**: Set `DEVCTL_GITHUB_OWNER` and `DEVCTL_GITHUB_REPO` (e.g. in `~/.bashrc` or `~/.zshrc`).
- **Custom manifest**: Set `DEVCTL_MANIFEST_URL` to a URL that serves the current manifest (e.g. a CDN that you update on each release).

## Usage

```bash
devctl ai-kit setup --repo <repo_url>
devctl ai-kit update
devctl ai-kit status
devctl ai-kit doctor
devctl list
devctl update-cli
```

## What is ai-kit? Default Offering & Extensibility

### What is ai-kit?

**ai-kit** is a **command domain** in devctl — a grouping of subcommands for a specific use case. In this case, syncing AI-assisted dev tools (e.g. Cursor rules, skills, configs) from a central repo to the developer’s machine.

- **`devctl ai-kit setup --repo <url>`** — Clone a repo, apply its protocols, register it.
- **`devctl ai-kit update`** — Pull latest and re-apply protocols.
- **`devctl ai-kit status`** — Show repo versions and drift.
- **`devctl ai-kit doctor`** — Validate configs and suggest fixes.

ai-kit is **repo-agnostic**: it works with any repo that includes a `protocol.yaml`. The repo defines what to sync, not the CLI.

### Default offering of this repo

| Component | Description |
|-----------|-------------|
| **CLI binary** | Single executable (`devctl`), self-updating |
| **Protocol engine** | Parses `protocol.yaml`, executes protocols (currently `file_sync`) |
| **Repo manager** | Clone/pull repos, slug from URL |
| **Backup** | Snapshot target before overwrite |
| **Versioning** | Track repos and versions in `state.json` |
| **ai-kit** | First implemented domain (setup, update, status, doctor) |
| **devspace / local** | Placeholder groups for future domains |

### How it scales for other projects

Any project can become a source that devctl syncs from:

1. **Add `protocol.yaml`** to the repo root.
2. **Publish the repo** (GitHub, GitLab, etc.).
3. **Users run** `devctl ai-kit setup --repo <url>`.

Example: org `Acme` maintains `acme/ai-configs` with Cursor rules. Developers run:

```bash
devctl ai-kit setup --repo https://github.com/acme/ai-configs
```

The same flow works for any org or repo — no hardcoded URLs. A developer can sync from multiple repos:

```bash
devctl ai-kit setup --repo https://github.com/acme/ai-configs
devctl ai-kit setup --repo https://github.com/other-org/cursor-rules
devctl list  # Shows both
```

### How to extend for other use cases

**1. New command domains** (e.g. `devctl devspace`, `devctl security`)

- Add `cli/devspace.py` (or similar) with a Click group and commands.
- Register in `main.py`: `cli.add_command(devspace, "devspace")`.
- Reuse `repo_manager`, `protocol_engine`, `versioning` where they fit.

**2. New protocol types** (beyond `file_sync`)

- In `protocol_engine.execute_protocol()`, add branches for new types:

```python
elif protocol.type == "env_sync":
    # Sync env vars from repo to ~/.devctl/env
    ...
elif protocol.type == "script_run":
    # Run a setup script defined in the repo
    ...
```

- The repo’s `protocol.yaml` then lists protocols with `type: env_sync` or `type: script_run`.

**3. Domain-specific logic**

- Domains can define custom behavior. For example, `devspace` could:
  - Use `protocol.yaml` to define containers/VMs to start.
  - Call Docker/Podman/colima.
  - Manage dev env lifecycle.

- `security` could:
  - Scan for secrets.
  - Enforce policies.
  - Use obligations to require certain configs or checks.

**4. Org-specific fork**

- Fork this repo and add domains/configs for your org.
- Build and release binaries with `DEVCTL_GITHUB_OWNER` / `DEVCTL_GITHUB_REPO` set for your org.
- Use as your internal developer control plane.

## Protocol Configuration

`protocol.yaml` or `protocol.yml` defines what to sync. It lives in the **root of the repo** you sync from.

When you run `devctl ai-kit setup --repo <url>`, devctl clones that repo and looks for `protocol.yaml` or `protocol.yml` at its root. If both exist, `protocol.yaml` takes precedence. The repo maintainer adds this file to define which configs to distribute.

**Supported repo URL formats:**
- HTTPS: `https://github.com/org/repo.git`
- SSH: `git@github.com:org/repo.git`

**Example `protocol.yaml` (in repo root):**

```yaml
version: v1
protocols:
  - name: cursor
    type: file_sync
    source: .cursor
    target: ~/.cursor
    obligations:
      - rules/security.json
    recommendations:
      - skills/debugging.md
```

### How protocol.yaml, Obligations, and Recommendations Work

**1. Loading `protocol.yaml`**

- Location: `protocol.yaml` or `protocol.yml` must be at the **root** of the cloned repo.
- Loading: `load_yaml()` uses PyYAML `safe_load` to parse the file.
- Validation:
  - Top level must be a dict with a `protocols` list.
  - Each protocol needs: `name`, `type`, `source`, `target`.
  - `obligations` and `recommendations` are optional lists (default: `[]`).
- Output: A list of `Protocol` dataclass instances.

**2. Protocol execution flow**

For each protocol (e.g. `file_sync`):

1. **Source / target resolution**
   - `source_path = repo_path / source` (e.g. `~/.devctl/repos/org-repo/.cursor`)
   - `target_path = expand_path(target)` (`~` expanded via `Path.expanduser`, e.g. `~/.cursor` → `/Users/you/.cursor`)

2. **Sync step**
   - For `file_sync`: merge `source` into `target` (file or directory).
   - Existing files in `target` are never deleted — only added/overwritten from `source`.
   - If target already exists: backup to `~/.devctl/backups/<slug>-<timestamp>/` first.

3. **Obligations check**
   - Each `obligations` entry is a path **relative to target**.
   - Example: `rules/security.json` → checked at `target_path / rules/security.json` (e.g. `~/.cursor/rules/security.json`).
   - If it does not exist after sync, it’s added to `missing_obligations`.
   - Obligations are **required**; setup/update still succeed but report them.

4. **Recommendations check**
   - Same logic, but for `recommendations`.
   - They are **optional**; missing ones are reported but not treated as failures.

**3. Path semantics**

| Field | Meaning | Example |
|-------|---------|---------|
| `source` | Path in the repo (relative to repo root) | `.cursor` → repo’s `.cursor/` |
| `target` | Where to sync on the machine (`~` allowed) | `~/.cursor` → user’s `~/.cursor` |
| `obligations` | Paths under `target` that must exist after sync | `rules/security.json` → `~/.cursor/rules/security.json` |
| `recommendations` | Paths under `target` that are nice to have | `skills/debugging.md` → `~/.cursor/skills/debugging.md` |

**4. When checks run**

- **setup / update**: After each sync, obligations and recommendations are checked. Any missing ones are printed to stderr (setup) or noted in update output.
- **status**: Loads the protocol file, then checks obligations and recommendations without syncing. Shows drift.
- **doctor**: Same as status but with explicit fix suggestions (e.g. re-run `devctl ai-kit update`).

**5. Example**

Repo layout:

```
repo/
  protocol.yaml
  .cursor/
    rules/
      security.json
    skills/
      debugging.md
```

`protocol.yaml`:

```yaml
protocols:
  - name: cursor
    type: file_sync
    source: .cursor
    target: ~/.cursor
    obligations: [rules/security.json]
    recommendations: [skills/debugging.md]
```

After `devctl ai-kit setup --repo <url>`:

- `repo/.cursor/` is copied to `~/.cursor/`.
- `~/.cursor/rules/security.json` exists → obligation satisfied.
- `~/.cursor/skills/debugging.md` exists → recommendation satisfied.

If `skills/debugging.md` were missing in the repo:

- Obligations pass.
- `~/.cursor/skills/debugging.md` would be missing → reported as a recommendation.

## Manifest, Update Check, and Auto-Update

### What the Manifest Stores

The manifest is a JSON file that tells devctl which version is latest and where to download the binary for each platform. It does **not** live on the local system — it is fetched from a remote URL each time a check runs.

**Manifest schema:**

```json
{
  "latest_version": "v1.2.0",
  "downloads": {
    "darwin-amd64": "https://github.com/OWNER/wi-devctl/releases/download/v1.2.0/devctl-darwin-amd64",
    "darwin-arm64": "https://github.com/OWNER/wi-devctl/releases/download/v1.2.0/devctl-darwin-arm64",
    "linux-amd64": "https://github.com/OWNER/wi-devctl/releases/download/v1.2.0/devctl-linux-amd64",
    "windows-amd64": "https://github.com/OWNER/wi-devctl/releases/download/v1.2.0/devctl-windows-amd64.exe"
  }
}
```

| Field | Meaning |
|-------|---------|
| `latest_version` | Semver-style tag (e.g. `v1.2.0`) of the newest release |
| `downloads` | Map of platform key → URL of the binary for that platform |

**Platform keys** (used as keys in `downloads`):

| Key | OS | Arch |
|-----|----|------|
| `darwin-amd64` | macOS (Intel) | x86_64 |
| `darwin-arm64` | macOS (Apple Silicon) | arm64 |
| `linux-amd64` | Linux | x86_64 |
| `linux-arm64` | Linux | arm64 |
| `windows-amd64` | Windows | x86_64 |

### Where the Manifest Comes From

Two sources (in order of precedence):

1. **Custom URL** — If `DEVCTL_MANIFEST_URL` is set, devctl fetches the manifest from that URL (e.g. S3, CDN, raw GitHub). The URL must return valid JSON.
2. **GitHub Releases API** — If not set, devctl calls `https://api.github.com/repos/{owner}/{repo}/releases/latest` and builds a manifest from the release:
   - `latest_version` = release `tag_name`
   - `downloads` = assets whose names match `devctl-{platform}` (e.g. `devctl-darwin-arm64`)

Configure owner/repo via `DEVCTL_GITHUB_OWNER` and `DEVCTL_GITHUB_REPO`.

### How the Local System Checks for Updates

On every devctl invocation (before running the requested command):

1. **Skip check** — If `DEVCTL_SKIP_AUTO_UPDATE=1`, the check is skipped.
2. **Fetch manifest** — Using the custom URL or GitHub API (see above).
3. **Platform detection** — `platform.system()` and `platform.machine()` are used to derive the platform key (e.g. `darwin-arm64`).
4. **Version comparison** — The `v` prefix is stripped and versions are compared as strings. If `latest_version` is greater than the bundled `__version__`, an update is available.
5. **Download URL lookup** — The manifest’s `downloads` dict is checked for the current platform key. If missing, no update is offered.

**Note:** No manifest or version data is stored locally. Each run does a fresh HTTP request.

### How Auto-Update Works

When an update is available (and not skipped):

1. **Download** — The binary at `downloads[platform_key]` is fetched via HTTP (60s timeout).
2. **Replace** — The new binary is written to a temp file, chmod 755, then `os.replace(temp, current_binary)` for atomic replacement.
3. **Re-exec** — `os.execv(exe, [exe] + sys.argv[1:])` restarts the process with the same arguments (the command you originally ran).
4. **No prompt** — The update runs silently. Failures are logged to stderr.

**Limitations:**

- Auto-update only works when running the **PyInstaller binary** (single executable). Running via `python -m devctl` or `pip install -e .` does not self-update (the process cannot safely replace the Python interpreter).
- GitHub 404 (no releases or wrong owner/repo) is ignored; other errors are logged.

### Manual Update

`devctl update-cli` forces an update:

- `force=True` — Always attempts update even if version appears current.
- Same flow as above: fetch manifest, download, replace, re-exec.

## Environment

- `DEVCTL_MANIFEST_URL` - Override manifest URL for updates
- `DEVCTL_SKIP_AUTO_UPDATE` - Set to `1` to disable auto-update
- `DEVCTL_VERBOSE` - Set to `1` to enable verbose output (same as `-v`)
- `DEVCTL_GITHUB_OWNER` - GitHub org/user (default: YOUR_ORG)
- `DEVCTL_GITHUB_REPO` - Repo name (default: wi-devctl)

## Verbose Mode

Use `-v` or `--verbose` to see what devctl is doing:

```bash
devctl -v ai-kit setup --repo <url>
devctl -v ai-kit update
```

Or set `DEVCTL_VERBOSE=1` for all commands.
