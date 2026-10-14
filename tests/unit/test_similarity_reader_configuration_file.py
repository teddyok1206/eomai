"""Actual no-follow descriptor/hash/race checks with explicitly synthetic root metadata.

Temporary files are not root-owned. Only ownership/directory protection observations
are substituted; these tests are not installed filesystem-privilege acceptance.
"""

from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest
from eom_catalog_service import similarity_read_runtime as module
from eom_catalog_service.similarity_read_runtime import SimilarityReaderRuntimeError
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_similarity_reader_configuration import document


@pytest.fixture
def protected(tmp_path, monkeypatch):
    path = tmp_path / "configuration.json"
    raw = canonical_json_bytes(document())
    path.write_bytes(raw)
    path.chmod(0o640)
    opened, closed, hooks = [], [], []

    def metadata(actual):
        names = (
            "st_dev",
            "st_ino",
            "st_uid",
            "st_gid",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        values = {name: getattr(actual, name) for name in names}
        values["st_uid"] = 0
        if stat.S_ISDIR(actual.st_mode):
            values["st_mode"] = stat.S_IFDIR | 0o755
        return SimpleNamespace(**values)

    def open_file(*args, **kwargs):
        fd = os.open(*args, **kwargs)
        opened.append(fd)
        return fd

    def close_file(fd):
        closed.append(fd)
        os.close(fd)

    def pread(fd, count, offset):
        result = os.pread(fd, count, offset)
        if hooks:
            hooks.pop(0)()
        return result

    io = SimpleNamespace(
        **{
            name: getattr(os, name)
            for name in (
                "O_RDONLY",
                "O_DIRECTORY",
                "O_NOFOLLOW",
                "O_CLOEXEC",
                "O_NONBLOCK",
            )
        }
    )
    io.open, io.close, io.pread = open_file, close_file, pread
    io.fstat = lambda fd: metadata(os.fstat(fd))
    io.stat = lambda *a, **kw: metadata(os.stat(*a, **kw))
    monkeypatch.setattr(module, "os", io)
    monkeypatch.setattr(module, "SIMILARITY_READER_CONFIGURATION_PATH", path)
    return SimpleNamespace(
        path=path,
        raw=raw,
        sha=sha256_bytes(raw),
        io=io,
        opened=opened,
        closed=closed,
        hooks=hooks,
        metadata=metadata,
    )


def test_exact_nonsecret_file_is_read_once_and_all_descriptors_are_closed(protected):
    value = protected
    pread = value.io.pread
    calls = []

    def observe(fd, count, offset):
        calls.append((count, offset))
        return pread(fd, count, offset)

    value.io.pread = observe
    assert module.read_similarity_reader_configuration(value.sha) == value.raw
    assert calls == [(64 * 1024 + 1, 0)]
    assert sorted(value.opened) == sorted(value.closed)


@pytest.mark.parametrize(
    "fault",
    (
        "owner",
        "writable",
        "setuid",
        "hardlink",
        "empty",
        "oversize",
        "symlink",
        "ancestor_symlink",
        "directory_owner",
        "directory_writable",
        "raw_hash",
    ),
)
def test_unprotected_or_changed_file_never_reaches_configuration_parse(protected, fault):
    value = protected
    original_fstat = value.io.fstat
    if fault in {"owner", "directory_owner", "directory_writable"}:

        def wrong(fd):
            observed = original_fstat(fd)
            directory = stat.S_ISDIR(observed.st_mode)
            if (fault == "owner" and not directory) or (fault == "directory_owner" and directory):
                observed.st_uid = os.getuid() + 100000
            elif fault == "directory_writable" and directory:
                observed.st_mode |= 0o022
            return observed

        value.io.fstat = wrong
    elif fault in {"writable", "setuid"}:
        value.path.chmod(0o666 if fault == "writable" else 0o4644)
    elif fault == "hardlink":
        os.link(value.path, value.path.with_name("alias"))
    elif fault == "empty":
        value.path.write_bytes(b"")
    elif fault == "oversize":
        value.path.write_bytes(b"x" * (64 * 1024 + 1))
    elif fault == "symlink":
        original = value.path.with_name("original")
        value.path.rename(original)
        value.path.symlink_to(original)
    elif fault == "ancestor_symlink":
        original = value.path.parent / "actual"
        original.mkdir()
        (original / "configuration.json").write_bytes(value.raw)
        linked = value.path.parent / "linked"
        linked.symlink_to(original, target_is_directory=True)
        module.SIMILARITY_READER_CONFIGURATION_PATH = linked / "configuration.json"
    else:
        value.sha = "sha256:" + "f" * 64
    with pytest.raises(SimilarityReaderRuntimeError):
        module.read_similarity_reader_configuration(value.sha)
    assert sorted(value.opened) == sorted(value.closed)


@pytest.mark.parametrize("fault", ("replace_leaf", "mutate_bytes", "replace_parent", "io_failure"))
def test_named_file_descriptor_and_ancestor_races_fail_closed(protected, fault):
    value = protected

    def change():
        if fault == "replace_leaf":
            value.path.rename(value.path.with_name("previous"))
            value.path.write_bytes(value.raw)
            value.path.chmod(0o640)
        elif fault == "mutate_bytes":
            value.path.write_bytes(value.raw + b"x")
        elif fault == "replace_parent":
            value.path.parent.rename(value.path.parent.with_name(value.path.parent.name + "-old"))
            value.path.parent.mkdir()
            value.path.write_bytes(value.raw)
            value.path.chmod(0o640)
        else:
            raise OSError("synthetic read failure, private path")

    value.hooks.append(change)
    with pytest.raises(SimilarityReaderRuntimeError):
        module.read_similarity_reader_configuration(value.sha)
    assert sorted(value.opened) == sorted(value.closed)


def test_bad_raw_sha_is_rejected_before_any_file_is_opened(protected):
    with pytest.raises(ValueError):
        module.read_similarity_reader_configuration("not-a-valid-sha")
    assert not protected.opened and not protected.closed
