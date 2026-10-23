"""One runtime member scan must not repeat shared-ancestor lookups per member."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)


def _snapshots(root: Path, count: int) -> tuple[NumericalRuntimeFileSnapshots, tuple[Path, ...]]:
    root.mkdir(mode=0o700)
    files = tuple(root / f"member-{index}.bin" for index in range(count))
    snapshots = NumericalRuntimeFileSnapshots(os.geteuid())
    for path in files:
        path.write_bytes(b"fixed")
        path.chmod(0o444)
        snapshots.observe_protected_member_identity(path)
    return snapshots, files


def test_shared_ancestors_are_checked_twice_not_per_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    snapshots, files = _snapshots(root, 64)
    seen: Counter[Path] = Counter()
    original = Path.lstat

    def counted(path: Path) -> os.stat_result:
        seen[path] += 1
        return original(path)

    monkeypatch.setattr(Path, "lstat", counted)
    snapshots.assert_unchanged()
    assert seen[root] == 2
    assert all(seen[path] == 1 for path in files)


def test_member_and_shared_ancestor_mutations_still_fail(tmp_path: Path) -> None:
    root = tmp_path / "protected"
    snapshots, files = _snapshots(root, 2)
    files[0].chmod(0o644)
    with pytest.raises(InstalledRuntimeProofError):
        snapshots.assert_unchanged()
    other_root = tmp_path / "other-protected"
    other_snapshots, _ = _snapshots(other_root, 2)
    other_root.chmod(0o750)
    with pytest.raises(InstalledRuntimeProofError):
        other_snapshots.assert_unchanged()
