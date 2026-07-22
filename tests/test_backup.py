"""Tests for run-level backup and retention."""

from pathlib import Path

import pytest

from devctl.core import backup


@pytest.fixture
def backups_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    monkeypatch.setattr(backup, "get_backups_dir", lambda: backups_dir)
    return backups_dir


def _make_run_backup(backups_dir: Path, slug: str, timestamp: str) -> Path:
    path = backups_dir / f"{slug}-run-{timestamp}"
    path.mkdir()
    (path / "marker.txt").write_text(timestamp)
    return path


def _make_legacy_backup(backups_dir: Path, slug: str, timestamp: str) -> Path:
    path = backups_dir / f"{slug}-{timestamp}"
    path.mkdir()
    (path / "marker.txt").write_text(timestamp)
    return path


def test_backup_timestamp_is_second_precision() -> None:
    ts = backup._backup_timestamp()
    assert len(ts) == 16  # YYYYMMDDTHHMMSSZ
    assert ts.endswith("Z")
    assert "T" in ts

    assert backup._parse_run_backup_name("org-repo-run-20260323T053124Z") == (
        "org-repo",
        "20260323T053124Z",
    )
    assert backup._parse_run_backup_name(
        "WorkIndia-Private-wi-ai-collab-kit-run-20260713T060758Z"
    ) == (
        "WorkIndia-Private-wi-ai-collab-kit",
        "20260713T060758Z",
    )
    assert backup._parse_backup_name("org-repo-20260323T053124Z") == (
        "org-repo",
        "20260323T053124Z",
    )
    assert backup._parse_backup_name("not-a-backup") is None
    assert backup._parse_run_backup_name("org-repo-20260323T053124Z") is None


def test_dedupe_backup_targets(tmp_path: Path) -> None:
    parent = tmp_path / "cursor"
    child = parent / "skills"
    other = tmp_path / "claude"
    parent.mkdir()
    child.mkdir(parents=True)
    other.mkdir()

    kept = backup.dedupe_backup_targets([child, parent, other, parent])
    assert parent in kept
    assert other in kept
    assert child not in kept
    assert len(kept) == 2


def test_prune_backups_keeps_newest_runs_per_slug(backups_home: Path) -> None:
    slug = "org-repo"
    oldest = _make_run_backup(backups_home, slug, "20260101T000000Z")
    second_oldest = _make_run_backup(backups_home, slug, "20260102T000000Z")
    keep_3 = _make_run_backup(backups_home, slug, "20260103T000000Z")
    keep_4 = _make_run_backup(backups_home, slug, "20260104T000000Z")
    newest = _make_run_backup(backups_home, slug, "20260105T000000Z")

    deleted = backup.prune_backups(slug=slug, env={"DEVCTL_BACKUP_RETENTION_COUNT": "3"})

    assert oldest in deleted
    assert second_oldest in deleted
    assert keep_3.exists()
    assert keep_4.exists()
    assert newest.exists()
    assert not oldest.exists()
    assert not second_oldest.exists()


def test_prune_backups_removes_legacy(backups_home: Path) -> None:
    slug = "org-repo"
    legacy = _make_legacy_backup(backups_home, slug, "20260101T000000Z")
    run = _make_run_backup(backups_home, slug, "20260102T000000Z")

    deleted = backup.prune_backups(slug=slug, env={"DEVCTL_BACKUP_RETENTION_COUNT": "3"})

    assert legacy in deleted
    assert not legacy.exists()
    assert run.exists()
    assert run not in deleted


def test_prune_backups_respects_slug_filter(backups_home: Path) -> None:
    old_a = _make_run_backup(backups_home, "repo-a", "20260101T000000Z")
    old_b = _make_run_backup(backups_home, "repo-b", "20260101T000000Z")
    _make_run_backup(backups_home, "repo-a", "20260102T000000Z")
    _make_run_backup(backups_home, "repo-b", "20260102T000000Z")

    deleted = backup.prune_backups(slug="repo-a", env={"DEVCTL_BACKUP_RETENTION_COUNT": "1"})

    assert deleted == [old_a]
    assert not old_a.exists()
    assert old_b.exists()


def test_prune_backups_disabled(backups_home: Path) -> None:
    old = _make_run_backup(backups_home, "org-repo", "20260101T000000Z")
    _make_run_backup(backups_home, "org-repo", "20260102T000000Z")

    deleted = backup.prune_backups(env={"DEVCTL_BACKUP_RETENTION_DISABLED": "1"})

    assert deleted == []
    assert old.exists()


def test_prune_backups_dry_run(backups_home: Path) -> None:
    old = _make_run_backup(backups_home, "org-repo", "20260101T000000Z")
    _make_run_backup(backups_home, "org-repo", "20260102T000000Z")

    deleted = backup.prune_backups(
        env={"DEVCTL_BACKUP_RETENTION_COUNT": "1"},
        dry_run=True,
    )

    assert deleted == [old]
    assert old.exists()


def test_backup_apply_run_single_manifest(backups_home: Path, tmp_path: Path) -> None:
    cursor = tmp_path / "cursor"
    skills = cursor / "skills"
    claude = tmp_path / "claude"
    cursor.mkdir()
    skills.mkdir()
    (skills / "a.md").write_text("skill")
    claude.mkdir()
    (claude / "x.md").write_text("x")

    result = backup.backup_apply_run([cursor, skills, claude], "org-repo")

    assert result is not None
    assert result.name.startswith("org-repo-run-")
    assert (result / "manifest.json").exists()
    import json

    manifest = json.loads((result / "manifest.json").read_text())
    paths = {t["path"] for t in manifest["targets"]}
    assert str(cursor) in paths
    assert str(claude) in paths
    assert str(skills) not in paths  # nested under cursor
    assert len(manifest["targets"]) == 2


def test_backup_apply_run_nested_symlink_not_followed(
    backups_home: Path, tmp_path: Path
) -> None:
    root = tmp_path / "cursor"
    root.mkdir()
    missing = tmp_path / "does-not-exist"
    link = root / "skills"
    link.symlink_to(missing)

    result = backup.backup_apply_run([root], "org-repo")

    assert result is not None
    content = result / "0" / "content"
    assert (content / "skills").is_symlink()
    assert os_readlink(content / "skills") == str(missing)


def os_readlink(path: Path) -> str:
    import os

    return os.readlink(path)


def test_restore_apply_run_restores_dir_file_symlink(
    backups_home: Path, tmp_path: Path
) -> None:
    real = tmp_path / "real-skills"
    real.mkdir()
    (real / "s.md").write_text("shared")

    cursor = tmp_path / "cursor"
    cursor.mkdir()
    (cursor / "rules.md").write_text("rule")
    skills_link = tmp_path / "skills-link"
    skills_link.symlink_to(real)
    alone = tmp_path / "alone.txt"
    alone.write_text("file")

    run_dir = backup.backup_apply_run([cursor, skills_link, alone], "org-repo")
    assert run_dir is not None

    # Mutate live paths
    (cursor / "rules.md").write_text("changed")
    skills_link.unlink()
    skills_link.mkdir()
    (skills_link / "junk").write_text("x")
    alone.write_text("changed")

    backup.restore_apply_run(run_dir)

    assert (cursor / "rules.md").read_text() == "rule"
    assert skills_link.is_symlink()
    assert skills_link.resolve() == real.resolve()
    assert alone.read_text() == "file"


def test_backup_target_creates_run_snapshot(backups_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "rules").mkdir()
    (target / "rules" / "a.md").write_text("rule")

    result = backup.backup_target(target, "org-repo")

    assert result is not None
    assert "-run-" in result.name
    assert (result / "0" / "content" / "rules" / "a.md").read_text() == "rule"


def test_backup_target_symlink_records_link_only(backups_home: Path, tmp_path: Path) -> None:
    """Symlink backup stores link metadata without deep-copying the resolved tree."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "big.txt").write_text("content")
    link = tmp_path / "link"
    link.symlink_to(real)

    result = backup.backup_target(link, "org-repo")

    assert result is not None
    assert (result / "0" / "SYMLINK_TARGET").read_text(encoding="utf-8") == str(real)
    assert not (result / "0" / "big.txt").exists()


def test_apply_protocols_one_run_backup_and_prunes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from devctl.core.protocol_engine import apply_protocols

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    monkeypatch.setattr(backup, "get_backups_dir", lambda: backups_dir)

    slug = "test-slug"
    for ts in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z", "20260104T000000Z"):
        _make_run_backup(backups_dir, slug, ts)

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "file.txt").write_text("new")
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.txt").write_text("old")
    (repo / "protocol.yaml").write_text(
        f"""
version: v1
protocols:
  - name: test
    type: file_sync
    source: src
    target: {target}
"""
    )

    apply_protocols(repo, slug, do_backup=True)

    remaining = sorted(p.name for p in backups_dir.iterdir() if p.is_dir())
    assert len(remaining) == 3
    assert all("-run-" in name for name in remaining)
    assert f"{slug}-run-20260101T000000Z" not in remaining
    assert f"{slug}-run-20260102T000000Z" not in remaining
