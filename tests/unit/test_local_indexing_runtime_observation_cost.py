"""Per-fence metadata operation counts; synthetic root metadata is not runtime admission."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_identity_service import local_indexing_runtime as runtime


def metadata(*, directory=False, inode=1):
    return SimpleNamespace(
        st_dev=1,
        st_ino=inode,
        st_mode=(0o040755 if directory else 0o100444),
        st_uid=0,
        st_gid=0,
        st_nlink=1,
        st_size=10,
        st_mtime_ns=100,
        st_ctime_ns=100,
    )


@pytest.fixture
def filesystem(monkeypatch):
    calls = Counter()
    values = {}
    real_lstat = Path.lstat

    def observe(path):
        if path not in values:
            return real_lstat(path)
        calls[path] += 1
        return values[path]

    monkeypatch.setattr(Path, "lstat", observe)
    monkeypatch.setattr(runtime, "_ROOT_UID", 0)
    return calls, values


@pytest.mark.parametrize("count", (1, 4, 512, 2048))
def test_epoch_observation_batches_distinct_parents_with_existing_symlink_checks(filesystem, count):
    calls, values = filesystem
    paths = tuple(Path("/opt/eom/runtime/pkg") / f"member-{index}.py" for index in range(count))
    parents = set().union(*(path.parents for path in paths))
    values.update((path, metadata(directory=True)) for path in parents)
    values.update((path, metadata(inode=index + 10)) for index, path in enumerate(paths))
    files = runtime._ProtectedFiles(1000)
    files.epochs = {path: runtime._epoch(values[path]) for path in paths}
    for observation in range(1, 3):
        files.assert_current()
        assert set(calls) == {*paths, *parents}
        assert {calls[path] for path in paths} == {observation}
        assert {calls[parent] for parent in parents} == {observation * 2}
        assert sum(calls.values()) == observation * (count + 2 * len(parents))
    # Exercise the former per-file traversal with the identical checks/metadata.
    # This reference loop changes no authority, byte or lifetime invariant.
    calls.clear()
    for path, expected in tuple(files.epochs.items()):
        files.ancestors(path)
        assert runtime._epoch(path.lstat()) == expected
    assert sum(calls.values()) == sum(2 * len(path.parents) + 1 for path in paths)
    assert count + 2 * len(parents) <= sum(calls.values())


@pytest.mark.parametrize(
    "fault", ("parent_owner", "parent_mode", "parent_kind", "parent_symlink", "file_epoch")
)
def test_next_fence_rechecks_shared_parents_and_every_file_epoch(filesystem, fault):
    calls, values = filesystem
    paths = (Path("/opt/eom/runtime/a.py"), Path("/opt/eom/runtime/b.py"))
    for path in paths:
        values[path] = metadata(inode=len(values) + 10)
        values.update((parent, metadata(directory=True)) for parent in path.parents)
    files = runtime._ProtectedFiles(1000)
    files.epochs = {path: runtime._epoch(values[path]) for path in paths}
    files.assert_current()
    if fault == "file_epoch":
        values[paths[1]].st_ino += 1
    else:
        parent = values[Path("/opt/eom")]
        if fault == "parent_owner":
            parent.st_uid = 12345
        elif fault == "parent_mode":
            parent.st_mode |= 0o022
        elif fault == "parent_symlink":
            parent.st_mode = 0o120777
        else:
            parent.st_mode = 0o100755
    with pytest.raises(runtime.IndexingRuntimeAdmissionError):
        files.assert_current()
    assert calls[Path("/opt/eom")] == (3 if fault in {"parent_kind", "parent_symlink"} else 4)


@pytest.mark.parametrize("path", (Path("relative/a.py"), Path("/opt/../etc/unsafe.py")))
def test_invalid_path_is_rejected_before_filesystem_access(filesystem, path):
    calls, _values = filesystem
    with pytest.raises(runtime.IndexingRuntimeAdmissionError):
        runtime._ProtectedFiles(1000).ancestors_many((path,))
    assert not calls


def test_loaded_module_aliases_do_not_repeat_physical_origin_checks(monkeypatch, filesystem):
    calls, values = filesystem
    prefix = Path("/opt/eom/runtime")
    path = prefix / "lib/runtime.py"
    values[path] = metadata()
    values.update((parent, metadata(directory=True)) for parent in path.parents)
    monkeypatch.setattr(runtime, "_PREFIX", prefix)
    monkeypatch.setattr(
        runtime,
        "sys",
        SimpleNamespace(
            modules={
                "runtime": SimpleNamespace(__file__=str(path)),
                "runtime_alias": SimpleNamespace(__file__=str(path)),
            }
        ),
    )
    runtime._loaded_code(runtime._ProtectedFiles(1000), Path("/opt/owner/site-packages"), set())
    assert set(calls.values()) == {2}
    assert set(calls) == {path, *path.parents}


@pytest.mark.parametrize("count", (1, 512, 4096))
def test_parent_path_construction_is_linear_in_files_and_distinct_parents(
    monkeypatch, filesystem, count
):
    calls, values = filesystem
    paths = tuple(Path("/opt/eom/runtime/pkg") / f"member-{index}.py" for index in range(count))
    parents = set().union(*(path.parents for path in paths))
    values.update((parent, metadata(directory=True)) for parent in parents)
    constructed = 0
    actual_parent = Path.parent.fget

    def parent(path):
        nonlocal constructed
        constructed += 1
        return actual_parent(path)

    monkeypatch.setattr(Path, "parent", property(parent))
    files = runtime._ProtectedFiles(1000)
    files.ancestors_many(paths)
    assert constructed == count + len(parents)
    assert calls == Counter({path: 2 for path in parents})
    # No filesystem result is retained: the same O(n+p) path walk must still
    # observe every parent again, including a newly substituted ancestor.
    values[Path("/opt/eom")].st_uid = 12345
    with pytest.raises(runtime.IndexingRuntimeAdmissionError):
        files.ancestors_many(paths)


@pytest.mark.parametrize(
    "name,origin,allowed",
    (
        ("eom_example", "/opt/owner/site-packages/eom_example/a.py", True),
        ("eom_example", "/opt/owner/site-packages/eom_example/unlisted.py", False),
        ("eom_example", "/opt/owner/site-packages-extra/eom_example/a.py", False),
        ("external", "/opt/eom/runtime/lib/a.py", True),
        ("external", "/opt/eom/runtime-extra/lib/a.py", False),
        ("external", "/opt/eom/runtime/../unsafe.py", False),
        ("eom_gpu_lease", "/opt/eom/runtime/lib/a.py", True),
        ("eom_example", "/opt/eom/runtime/lib/a.py", False),
    ),
)
def test_module_origin_uses_component_boundaries_not_textual_prefixes(
    monkeypatch, filesystem, name, origin, allowed
):
    _calls, values = filesystem
    path = Path(origin)
    values[path] = metadata()
    values.update((parent, metadata(directory=True)) for parent in path.parents)
    monkeypatch.setattr(runtime, "_PREFIX", Path("/opt/eom/runtime"))
    monkeypatch.setattr(
        runtime, "sys", SimpleNamespace(modules={name: SimpleNamespace(__file__=origin)})
    )
    files = runtime._ProtectedFiles(1000)
    if allowed:
        runtime._loaded_code(files, Path("/opt/owner/site-packages"), {"eom_example/a.py"})
    else:
        with pytest.raises(runtime.IndexingRuntimeAdmissionError):
            runtime._loaded_code(files, Path("/opt/owner/site-packages"), {"eom_example/a.py"})
