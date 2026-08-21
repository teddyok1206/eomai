from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scripts.hwpx.python_runtime_layout import (
    PythonRuntimeLayoutError,
    inventory_layout,
    normalize_layout,
    verify_layout,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "site-packages"
    dependency = root / "click"
    dependency.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    dependency.chmod(0o700)
    module = dependency / "exceptions.py"
    module.write_text("class Abort(Exception): pass\n", encoding="utf-8")
    module.chmod(0o600)
    executable_module = dependency / "accidentally-executable.py"
    executable_module.write_text("VALUE = 1\n", encoding="utf-8")
    executable_module.chmod(0o755)
    console = tmp_path / "bin/eom-hwpx"
    console.parent.mkdir()
    console.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    console.chmod(0o755)
    return root, dependency, module, console


def test_restrictive_dependency_is_rejected_then_normalized_for_distinct_identity(
    tmp_path: Path,
) -> None:
    root, dependency, module, console = _fixture(tmp_path)
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_LAYOUT_MODE_MISMATCH"):
        verify_layout(
            root,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            console_scripts=(console,),
        )

    first = normalize_layout(
        root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        console_scripts=(console,),
    )
    assert first.changes == 4
    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    assert stat.S_IMODE(dependency.stat().st_mode) == 0o755
    assert stat.S_IMODE(module.stat().st_mode) == 0o644
    assert stat.S_IMODE((dependency / "accidentally-executable.py").stat().st_mode) == 0o644
    assert stat.S_IMODE(console.stat().st_mode) == 0o755

    result = verify_layout(
        root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        console_scripts=(console,),
        service_uid=os.getuid() + 10_000,
        service_gids=set(),
    )
    assert result.entries == 4


def test_normalization_is_idempotent(tmp_path: Path) -> None:
    root, _dependency, _module, console = _fixture(tmp_path)
    normalize_layout(
        root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        console_scripts=(console,),
    )
    second = normalize_layout(
        root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        console_scripts=(console,),
    )
    assert second.changes == 0


def test_contained_symlink_is_preserved_and_escape_is_rejected(tmp_path: Path) -> None:
    root, dependency, module, console = _fixture(tmp_path)
    normalize_layout(
        root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        console_scripts=(console,),
    )
    inside = dependency / "inside.py"
    inside.symlink_to(module.name)
    inventory_layout(root, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert inside.is_symlink()

    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 2\n", encoding="utf-8")
    (dependency / "escape.py").symlink_to(outside)
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_LAYOUT_SYMLINK_ESCAPE"):
        inventory_layout(root, expected_uid=os.getuid(), expected_gid=os.getgid())


def test_special_file_fails_closed(tmp_path: Path) -> None:
    root, dependency, _module, console = _fixture(tmp_path)
    normalize_layout(
        root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        console_scripts=(console,),
    )
    os.mkfifo(dependency / "unexpected.fifo")
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_LAYOUT_SPECIAL_FILE"):
        inventory_layout(root, expected_uid=os.getuid(), expected_gid=os.getgid())
