"""Tests for protocol_engine."""

import tempfile
from pathlib import Path

import pytest

from devctl.core.protocol_engine import (
    Protocol,
    apply_protocols,
    load_protocols,
    execute_protocol,
)


def test_load_protocols_valid(tmp_path: Path) -> None:
    """Load valid protocol.yaml."""
    (tmp_path / "protocol.yaml").write_text("""
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
""")
    version, protocols = load_protocols(tmp_path)
    assert version == "v1"
    assert len(protocols) == 1
    p = protocols[0]
    assert p.name == "cursor"
    assert p.type == "file_sync"
    assert p.source == ".cursor"
    assert p.target == "~/.cursor"
    assert p.obligations == ["rules/security.json"]
    assert p.recommendations == ["skills/debugging.md"]


def test_load_protocols_yml(tmp_path: Path) -> None:
    """Load valid protocol.yml (alternative to protocol.yaml)."""
    (tmp_path / "protocol.yml").write_text("""
version: v2
protocols:
  - name: test
    type: file_sync
    source: src
    target: tgt
""")
    version, protocols = load_protocols(tmp_path)
    assert version == "v2"
    assert len(protocols) == 1
    assert protocols[0].name == "test"


def test_load_protocols_yaml_precedence(tmp_path: Path) -> None:
    """protocol.yaml takes precedence over protocol.yml when both exist."""
    (tmp_path / "protocol.yml").write_text("version: v1\nprotocols: []")
    (tmp_path / "protocol.yaml").write_text("version: v2\nprotocols: []")
    version, _ = load_protocols(tmp_path)
    assert version == "v2"


def test_load_protocols_missing_file(tmp_path: Path) -> None:
    """Raise when neither protocol.yaml nor protocol.yml exists."""
    with pytest.raises(FileNotFoundError):
        load_protocols(tmp_path)


def test_load_protocols_invalid(tmp_path: Path) -> None:
    """Raise when protocol.yaml invalid."""
    (tmp_path / "protocol.yaml").write_text("protocols: not a list")
    with pytest.raises(ValueError):
        load_protocols(tmp_path)


def test_execute_protocol_file_sync(tmp_path: Path) -> None:
    """Execute file_sync protocol."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_text("hello")
    (source_dir / "subdir").mkdir()
    (source_dir / "subdir" / "nested.txt").write_text("nested")

    target = tmp_path / "target"
    protocol = Protocol(
        name="test",
        type="file_sync",
        source="source",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    repo_path = tmp_path
    missing_obl, missing_rec = execute_protocol(protocol, repo_path, "test", do_backup=False)

    assert (target / "file.txt").exists()
    assert (target / "file.txt").read_text() == "hello"
    assert (target / "subdir" / "nested.txt").exists()
    assert missing_obl == []
    assert missing_rec == []


def test_execute_protocol_merge_preserves_existing(tmp_path: Path) -> None:
    """Merge into existing target without deleting existing files."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "from_repo.txt").write_text("from repo")
    (source_dir / "shared.txt").write_text("overwritten")

    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.txt").write_text("keep me")
    (target / "shared.txt").write_text("old value")

    protocol = Protocol(
        name="test",
        type="file_sync",
        source="source",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    execute_protocol(protocol, tmp_path, "test", do_backup=False)

    assert (target / "from_repo.txt").read_text() == "from repo"
    assert (target / "shared.txt").read_text() == "overwritten"
    assert (target / "existing.txt").exists()
    assert (target / "existing.txt").read_text() == "keep me"


def test_execute_protocol_unknown_type(tmp_path: Path) -> None:
    """Raise for unknown protocol type."""
    (tmp_path / "x").write_text("dummy")
    protocol = Protocol(
        name="test",
        type="unknown",
        source="x",
        target=str(tmp_path / "y"),
        obligations=[],
        recommendations=[],
    )
    with pytest.raises(ValueError, match="Unknown protocol type"):
        execute_protocol(protocol, tmp_path, "test", do_backup=False)


def test_execute_protocol_source_missing(tmp_path: Path) -> None:
    """Raise when source path does not exist."""
    protocol = Protocol(
        name="test",
        type="file_sync",
        source="nope",
        target=str(tmp_path / "tgt"),
        obligations=[],
        recommendations=[],
    )
    with pytest.raises(FileNotFoundError, match="Source not found"):
        execute_protocol(protocol, tmp_path, "slug", do_backup=False)


def test_execute_protocol_obligations_satisfied(tmp_path: Path) -> None:
    """No missing obligations when synced files exist."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "rules").mkdir()
    (src / "rules" / "sec.json").write_text("{}")
    tgt = tmp_path / "out"
    protocol = Protocol(
        name="c",
        type="file_sync",
        source="src",
        target=str(tgt),
        obligations=["rules/sec.json"],
        recommendations=["opt/readme.md"],
    )
    miss_o, miss_r = execute_protocol(protocol, tmp_path, "s", do_backup=False)
    assert miss_o == []
    assert miss_r == [str(tgt / "opt" / "readme.md")]


def test_execute_protocol_obligation_missing(tmp_path: Path) -> None:
    """Report obligation path missing under target after sync."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x")
    tgt = tmp_path / "out"
    protocol = Protocol(
        name="c",
        type="file_sync",
        source="src",
        target=str(tgt),
        obligations=["rules/must-exist.json"],
        recommendations=[],
    )
    miss_o, miss_r = execute_protocol(protocol, tmp_path, "s", do_backup=False)
    assert len(miss_o) == 1
    assert "must-exist.json" in miss_o[0]
    assert miss_r == []


def test_load_protocols_protocol_entry_invalid(tmp_path: Path) -> None:
    """protocols list entries must be objects."""
    (tmp_path / "protocol.yaml").write_text(
        """
version: v1
protocols:
  - not_an_object
"""
    )
    with pytest.raises(ValueError, match="must be an object"):
        load_protocols(tmp_path)


def test_load_protocols_missing_required_fields(tmp_path: Path) -> None:
    """Each protocol needs name, type, source, target."""
    (tmp_path / "protocol.yaml").write_text(
        """
version: v1
protocols:
  - name: only-name
    type: file_sync
"""
    )
    with pytest.raises(ValueError, match="requires name, type, source, target"):
        load_protocols(tmp_path)


def test_apply_protocols_aggregates_missing(tmp_path: Path) -> None:
    """apply_protocols merges missing obligation lists across protocols."""
    out1 = tmp_path / "OUT1"
    out2 = tmp_path / "OUT2"
    (tmp_path / "protocol.yaml").write_text(
        f"""
version: v1
protocols:
  - name: one
    type: file_sync
    source: s1
    target: {out1}
    obligations: [missing1.txt]
  - name: two
    type: file_sync
    source: s2
    target: {out2}
    obligations: [missing2.txt]
"""
    )
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "f.txt").write_text("a")
    (tmp_path / "s2").mkdir()
    (tmp_path / "s2" / "g.txt").write_text("b")

    ver, protos, miss_o, miss_r = apply_protocols(tmp_path, "slug", do_backup=False)
    assert ver == "v1"
    assert len(protos) == 2
    assert len(miss_o) == 2
    assert any("missing1.txt" in m for m in miss_o)
    assert any("missing2.txt" in m for m in miss_o)


def test_execute_protocol_symlink_sync_create(tmp_path: Path) -> None:
    """symlink_sync creates a directory symlink to source."""
    source = tmp_path / "common" / "skills"
    source.mkdir(parents=True)
    (source / "demo").mkdir()
    (source / "demo" / "SKILL.md").write_text("hi")
    target = tmp_path / "home" / "skills"

    protocol = Protocol(
        name="skills",
        type="symlink_sync",
        source="common/skills",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    missing_obl, missing_rec = execute_protocol(protocol, tmp_path, "test", do_backup=False)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert (target / "demo" / "SKILL.md").read_text() == "hi"
    assert missing_obl == []
    assert missing_rec == []


def test_execute_protocol_symlink_sync_idempotent(tmp_path: Path) -> None:
    """Re-applying symlink_sync when already correct is a no-op."""
    source = tmp_path / "common" / "skills"
    source.mkdir(parents=True)
    target = tmp_path / "home" / "skills"
    target.parent.mkdir(parents=True)
    target.symlink_to(source.resolve())

    protocol = Protocol(
        name="skills",
        type="symlink_sync",
        source="common/skills",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    execute_protocol(protocol, tmp_path, "test", do_backup=False)
    execute_protocol(protocol, tmp_path, "test", do_backup=False)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_execute_protocol_symlink_sync_replaces_real_dir(tmp_path: Path) -> None:
    """symlink_sync replaces a prior real directory (migration from file_sync)."""
    source = tmp_path / "common" / "skills"
    source.mkdir(parents=True)
    (source / "from_common.txt").write_text("common")

    target = tmp_path / "home" / "skills"
    target.mkdir(parents=True)
    (target / "old_copy.txt").write_text("stale")

    protocol = Protocol(
        name="skills",
        type="symlink_sync",
        source="common/skills",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    execute_protocol(protocol, tmp_path, "test", do_backup=False)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert (target / "from_common.txt").read_text() == "common"
    assert not (target / "old_copy.txt").exists()


def test_execute_protocol_symlink_sync_repairs_broken_link(tmp_path: Path) -> None:
    """symlink_sync replaces a broken symlink."""
    source = tmp_path / "common" / "skills"
    source.mkdir(parents=True)

    target = tmp_path / "home" / "skills"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "does-not-exist")

    protocol = Protocol(
        name="skills",
        type="symlink_sync",
        source="common/skills",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    execute_protocol(protocol, tmp_path, "test", do_backup=False)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_execute_protocol_symlink_sync_retargets_wrong_link(tmp_path: Path) -> None:
    """symlink_sync replaces a symlink that points at the wrong path."""
    source = tmp_path / "common" / "skills"
    source.mkdir(parents=True)
    wrong = tmp_path / "other"
    wrong.mkdir()

    target = tmp_path / "home" / "skills"
    target.parent.mkdir(parents=True)
    target.symlink_to(wrong.resolve())

    protocol = Protocol(
        name="skills",
        type="symlink_sync",
        source="common/skills",
        target=str(target),
        obligations=[],
        recommendations=[],
    )
    execute_protocol(protocol, tmp_path, "test", do_backup=False)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_check_symlink_integrity(tmp_path: Path) -> None:
    """check_symlink_integrity reports missing, wrong, and ok states."""
    from devctl.core.protocol_engine import check_symlink_integrity

    source = tmp_path / "common" / "skills"
    source.mkdir(parents=True)
    target = tmp_path / "home" / "skills"
    protocol = Protocol(
        name="skills",
        type="symlink_sync",
        source="common/skills",
        target=str(target),
        obligations=[],
        recommendations=[],
    )

    assert check_symlink_integrity(protocol, tmp_path) is not None

    target.parent.mkdir(parents=True)
    target.mkdir()
    assert "not a symlink" in (check_symlink_integrity(protocol, tmp_path) or "")

    target.rmdir()
    target.symlink_to(source.resolve())
    assert check_symlink_integrity(protocol, tmp_path) is None

    file_sync = Protocol(
        name="c",
        type="file_sync",
        source="common/skills",
        target=str(tmp_path / "out"),
        obligations=[],
        recommendations=[],
    )
    assert check_symlink_integrity(file_sync, tmp_path) is None
