# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CHANGELOG.md` for release history
- **Create release tag** GitHub Actions workflow (`workflow_dispatch`) for scalable releases

### Fixed

- Bundle `certifi` CA certificates in PyInstaller builds so auto-update HTTPS works on macOS without `SSL_CERT_FILE`
- Use explicit certifi-backed SSL contexts for all updater GitHub API/download requests

### Changed

- PyInstaller release build now uses `--hidden-import certifi --collect-all certifi`

## [0.4.0] - 2026-07-15

### Added

- Automatic backup retention: keep the newest 3 config snapshots per repo slug after each apply/sync
- `devctl ai-kit prune-backups` command with `--dry-run`
- `DEVCTL_BACKUP_RETENTION_COUNT` and `DEVCTL_BACKUP_RETENTION_DISABLED` environment variables
- Tests for backup retention (`tests/test_backup.py`)

### Fixed

- Unbounded growth of `~/.devctl/backups` from hourly background sync

## [0.3.0] - 2026-07-14

### Added

- `devctl ai-kit background-sync-status` for inspecting launchd/cron background sync
- Background sync logging to `~/.devctl/logs/background-sync.log`
- Verbose sync output via `devctl ai-kit sync -v`

### Changed

- Improved background sync install docs and macOS launchd troubleshooting in README

## [0.2.0] - 2026-07-13

### Added

- Configurable config sync interval via `DEVCTL_CONFIG_SYNC_INTERVAL_MINUTES` and `DEVCTL_CONFIG_SYNC_INTERVAL_HOURS`
- Expanded automated test coverage for config sync, CLI, and background sync

### Changed

- Improved config sync rate limiting and logging behavior

## [0.1.0] - 2026-07-12

### Added

- Initial public release of the `devctl` CLI
- Protocol-driven `ai-kit` setup, sync, and update
- Hourly background sync via launchd (macOS) or cron (Linux)
- Self-updating binary from GitHub Releases
- Backup before overwrite when applying protocols
- One-shot `install.sh` with optional `DEVCTL_AI_KIT_REPO` and `DEVCTL_AI_KIT_BACKGROUND_SYNC`

[Unreleased]: https://github.com/workindia/wi-devctl/compare/v0.4.0...main
[0.4.0]: https://github.com/workindia/wi-devctl/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/workindia/wi-devctl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/workindia/wi-devctl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/workindia/wi-devctl/releases/tag/v0.1.0
