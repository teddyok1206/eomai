from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.hwpx.python_runtime_layout import (
    PythonRuntimeLayoutError,
    inventory_layout,
    normalize_layout,
    normalize_runtime_executables,
    normalize_runtime_libraries,
    verify_layout,
    verify_runtime_executables,
    verify_runtime_libraries,
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


def _node_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    boundary = tmp_path / "eom-hwpx"
    binary_directory = boundary / "bin"
    binary_directory.mkdir(parents=True)
    node = binary_directory / "node"
    node.write_text("#!/bin/sh\nprintf 'v20.17.0\\n'\n", encoding="utf-8")
    node.chmod(0o700)
    data = boundary / "node-runtime.json"
    data.write_text('{"version":"20.17.0"}\n', encoding="utf-8")
    data.chmod(0o600)
    package_cache_node = tmp_path / "package-cache-node"
    os.link(node, package_cache_node)
    return boundary, node, data, package_cache_node


def test_node_hardlink_is_privately_materialized_for_service_execution(
    tmp_path: Path,
) -> None:
    boundary, node, data, package_cache_node = _node_fixture(tmp_path)
    original = node.read_bytes()
    with pytest.raises(
        PythonRuntimeLayoutError,
        match="HWPX_RUNTIME_EXECUTABLE_MODE_MISMATCH",
    ):
        verify_runtime_executables(
            (node,),
            boundary=boundary,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )

    first = normalize_runtime_executables(
        (node,),
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert first.changes == 1
    assert node.read_bytes() == original
    assert stat.S_IMODE(node.stat().st_mode) == 0o755
    assert node.stat().st_ino != package_cache_node.stat().st_ino
    assert stat.S_IMODE(package_cache_node.stat().st_mode) == 0o700
    assert stat.S_IMODE(data.stat().st_mode) == 0o600
    assert (
        subprocess.run(
            [node, "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "v20.17.0"
    )
    verify_runtime_executables(
        (node,),
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        service_uid=os.getuid() + 10_000,
        service_gids=set(),
    )

    second = normalize_runtime_executables(
        (node,),
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert second.changes == 0


def test_node_symlink_must_resolve_inside_runtime_boundary(tmp_path: Path) -> None:
    boundary = tmp_path / "eom-hwpx"
    binary_directory = boundary / "bin"
    binary_directory.mkdir(parents=True)
    target = binary_directory / "node-20"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o700)
    node = binary_directory / "node"
    node.symlink_to(target.name)
    normalize_runtime_executables(
        (node,),
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert node.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o755

    outside = tmp_path / "outside-node"
    outside.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    outside.chmod(0o700)
    node.unlink()
    node.symlink_to(outside)
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_LAYOUT_SYMLINK_ESCAPE"):
        normalize_runtime_executables(
            (node,),
            boundary=boundary,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_node_special_file_fails_closed(tmp_path: Path) -> None:
    boundary = tmp_path / "eom-hwpx"
    binary_directory = boundary / "bin"
    binary_directory.mkdir(parents=True)
    node = binary_directory / "node"
    os.mkfifo(node)
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_FILE_UNSAFE"):
        normalize_runtime_executables(
            (node,),
            boundary=boundary,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def _shared_library_fixture(
    tmp_path: Path,
) -> tuple[Path, tuple[Path, ...], tuple[Path, ...], Path]:
    boundary = tmp_path / "eom-hwpx"
    library_directory = boundary / "lib"
    cache_directory = tmp_path / "package-cache"
    library_directory.mkdir(parents=True)
    cache_directory.mkdir()
    environment_libraries: list[Path] = []
    cache_libraries: list[Path] = []
    for name in ("libnode.so.115", "libuv.so.1.0.0"):
        cache_library = cache_directory / name
        cache_library.write_bytes((name + "\n").encode())
        cache_library.chmod(0o700)
        environment_library = library_directory / name
        os.link(cache_library, environment_library)
        environment_libraries.append(environment_library)
        cache_libraries.append(cache_library)
    readable_library = library_directory / "libcrypto.so.3"
    readable_library.write_bytes(b"already-readable\n")
    readable_library.chmod(0o644)
    return (
        boundary,
        tuple(environment_libraries),
        tuple(cache_libraries),
        readable_library,
    )


def test_node_executable_is_insufficient_without_readable_library_closure(
    tmp_path: Path,
) -> None:
    boundary, environment_libraries, cache_libraries, readable_library = _shared_library_fixture(
        tmp_path
    )
    all_libraries = (*environment_libraries, readable_library)
    original_cache = {
        path.name: (path.stat().st_ino, path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in cache_libraries
    }
    with pytest.raises(
        PythonRuntimeLayoutError,
        match="HWPX_RUNTIME_LIBRARY_ACCESS_MISMATCH",
    ):
        verify_runtime_libraries(
            all_libraries,
            boundary=boundary,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            service_uid=os.getuid() + 10_000,
            service_gids=set(),
        )

    first = normalize_runtime_libraries(
        all_libraries,
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        service_uid=os.getuid() + 10_000,
        service_gids=set(),
    )
    assert first.changes == 2
    assert stat.S_IMODE(readable_library.stat().st_mode) == 0o644
    for environment_library, cache_library in zip(
        environment_libraries, cache_libraries, strict=True
    ):
        cache_inode, cache_bytes, cache_mode = original_cache[cache_library.name]
        assert environment_library.stat().st_ino != cache_inode
        assert stat.S_IMODE(environment_library.stat().st_mode) == 0o755
        assert environment_library.read_bytes() == cache_bytes
        assert cache_library.stat().st_ino == cache_inode
        assert cache_library.read_bytes() == cache_bytes
        assert stat.S_IMODE(cache_library.stat().st_mode) == cache_mode == 0o700

    verify_runtime_libraries(
        all_libraries,
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        service_uid=os.getuid() + 10_000,
        service_gids=set(),
    )
    second = normalize_runtime_libraries(
        all_libraries,
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        service_uid=os.getuid() + 10_000,
        service_gids=set(),
    )
    assert second.changes == 0


def test_shared_library_symlink_must_resolve_inside_runtime_boundary(tmp_path: Path) -> None:
    boundary = tmp_path / "eom-hwpx"
    library_directory = boundary / "lib"
    library_directory.mkdir(parents=True)
    target = library_directory / "libnode.so.115.0"
    target.write_bytes(b"node-library\n")
    target.chmod(0o700)
    library = library_directory / "libnode.so.115"
    library.symlink_to(target.name)
    normalize_runtime_libraries(
        (library,),
        boundary=boundary,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        service_uid=os.getuid() + 10_000,
        service_gids=set(),
    )
    assert library.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o755

    outside = tmp_path / "outside-library"
    outside.write_bytes(b"outside\n")
    outside.chmod(0o700)
    library.unlink()
    library.symlink_to(outside)
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_LAYOUT_SYMLINK_ESCAPE"):
        normalize_runtime_libraries(
            (library,),
            boundary=boundary,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            service_uid=os.getuid() + 10_000,
            service_gids=set(),
        )


def test_shared_library_special_file_fails_closed(tmp_path: Path) -> None:
    boundary = tmp_path / "eom-hwpx"
    library_directory = boundary / "lib"
    library_directory.mkdir(parents=True)
    library = library_directory / "libnode.so.115"
    os.mkfifo(library)
    with pytest.raises(PythonRuntimeLayoutError, match="HWPX_RUNTIME_FILE_UNSAFE"):
        normalize_runtime_libraries(
            (library,),
            boundary=boundary,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            service_uid=os.getuid() + 10_000,
            service_gids=set(),
        )
