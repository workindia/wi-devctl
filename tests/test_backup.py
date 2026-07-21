"""Tests for backup retention."""

from pathlib import Path

import pytest

from devctl.core import backup


@pytest.fixture
def backups_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    monkeypatch.setattr(backup, "get_backups_dir", lambda: backups_dir)
    return backups_dir


def _make_backup(backups_dir: Path, slug: str, timestamp: str) -> Path:
    path = backups_dir / f"{slug}-{timestamp}"
    path.mkdir()
    (path / "marker.txt").write_text(timestamp)
    return path


def test_parse_backup_name() -> None:
    assert backup._parse_backup_name("org-repo-20260323T053124Z") == (
        "org-repo",
        "20260323T053124Z",
    )
    assert backup._parse_backup_name("WorkIndia-Private-wi-ai-collab-kit-20260713T060758Z") == (
        "WorkIndia-Private-wi-ai-collab-kit",
        "20260713T060758Z",
    )
    assert backup._parse_backup_name("not-a-backup") is None


def test_prune_backups_keeps_newest_per_slug(backups_home: Path) -> None:
    slug = "org-repo"
    oldest = _make_backup(backups_home, slug, "20260101T000000Z")
    second_oldest = _make_backup(backups_home, slug, "20260102T000000Z")
    keep_3 = _make_backup(backups_home, slug, "20260103T000000Z")
    keep_4 = _make_backup(backups_home, slug, "20260104T000000Z")
    newest = _make_backup(backups_home, slug, "20260105T000000Z")

    deleted = backup.prune_backups(slug=slug, env={"DEVCTL_BACKUP_RETENTION_COUNT": "3"})

    assert oldest in deleted
    assert second_oldest in deleted
    assert keep_3.exists()
    assert keep_4.exists()
    assert newest.exists()
    assert not oldest.exists()
    assert not second_oldest.exists()


def test_prune_backups_respects_slug_filter(backups_home: Path) -> None:
    old_a = _make_backup(backups_home, "repo-a", "20260101T000000Z")
    old_b = _make_backup(backups_home, "repo-b", "20260101T000000Z")
    _make_backup(backups_home, "repo-a", "20260102T000000Z")
    _make_backup(backups_home, "repo-b", "20260102T000000Z")

    deleted = backup.prune_backups(slug="repo-a", env={"DEVCTL_BACKUP_RETENTION_COUNT": "1"})

    assert deleted == [old_a]
    assert not old_a.exists()
    assert old_b.exists()


def test_prune_backups_disabled(backups_home: Path) -> None:
    old = _make_backup(backups_home, "org-repo", "20260101T000000Z")
    _make_backup(backups_home, "org-repo", "20260102T000000Z")

    deleted = backup.prune_backups(env={"DEVCTL_BACKUP_RETENTION_DISABLED": "1"})

    assert deleted == []
    assert old.exists()


def test_prune_backups_dry_run(backups_home: Path) -> None:
    old = _make_backup(backups_home, "org-repo", "20260101T000000Z")
    _make_backup(backups_home, "org-repo", "20260102T000000Z")

    deleted = backup.prune_backups(
        env={"DEVCTL_BACKUP_RETENTION_COUNT": "1"},
        dry_run=True,
    )

    assert deleted == [old]
    assert old.exists()


def test_backup_target_creates_snapshot(backups_home: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "rules").mkdir()
    (target / "rules" / "a.md").write_text("rule")

    result = backup.backup_target(target, "org-repo")

    assert result is not None
    assert result.exists()
    assert (result / "rules" / "a.md").read_text() == "rule"


def test_backup_target_symlink_records_link_only(backups_home: Path, tmp_path: Path) -> None:
    """Symlink backup stores link metadata without deep-copying the resolved tree."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "big.txt").write_text("content")
    link = tmp_path / "link"
    link.symlink_to(real)

    result = backup.backup_target(link, "org-repo")

    assert result is not None
    assert (result / "SYMLINK_TARGET").read_text(encoding="utf-8") == str(real)
    assert not (result / "big.txt").exists()


def test_backup_target_unique_paths_per_call(backups_home: Path, tmp_path: Path) -> None:
    """Multiple backups in one run get distinct directory names (microsecond timestamps)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "x").write_text("a")
    (b / "y").write_text("b")

    path1 = backup.backup_target(a, "slug")
    path2 = backup.backup_target(b, "slug")

    assert path1 is not None and path2 is not None
    assert path1 != path2


def test_apply_protocols_prunes_old_backups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from devctl.core.protocol_engine import apply_protocols

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    monkeypatch.setattr(backup, "get_backups_dir", lambda: backups_dir)

    slug = "test-slug"
    for ts in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z", "20260104T000000Z"):
        _make_backup(backups_dir, slug, ts)

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
    assert "test-slug-20260101T000000Z" not in remaining
    assert "test-slug-20260102T000000Z" not in remaining
    assert any(name.startswith("test-slug-2026") and name.endswith("Z") for name in remaining)
