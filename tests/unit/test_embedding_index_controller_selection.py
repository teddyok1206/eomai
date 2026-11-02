"""Purpose-only compatible controller choice; no root/GPU/model/service side effects."""

from __future__ import annotations

import hashlib
import stat
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_index_controller_selection as selection

OLD = "a" * 40
CURRENT = "b" * 40
ATTEMPT = "c" * 32
RAW = b"# independently pinned immutable bootstrap\n"


class Delegated(BaseException):
    pass


@pytest.fixture
def ports(monkeypatch):
    state = SimpleNamespace(purpose="INDEX", faults=set(), rechecked=False)
    leaf = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_uid=0,
        st_gid=0,
        st_mode=stat.S_IFREG | 0o444,
        st_nlink=1,
        st_size=len(RAW),
        st_mtime_ns=3,
        st_ctime_ns=4,
    )

    class PinnedPath:
        parents = (
            SimpleNamespace(
                lstat=lambda: SimpleNamespace(
                    st_mode=stat.S_IFDIR | (0o777 if "parent" in state.faults else 0o755),
                    st_uid=0,
                )
            ),
        )

        def __truediv__(self, member):
            assert member in {OLD, "prepare_native_index.py"}
            return self

        def lstat(self):
            return (
                SimpleNamespace(**(vars(leaf) | {"st_ino": 9})) if "path" in state.faults else leaf
            )

        def __str__(self):
            return f"/opt/eom/embedding-owner-releases/{OLD}/prepare_native_index.py"

    def read_control(attempt):
        assert attempt == ATTEMPT
        if "allocation" in state.faults:
            raise ValueError("original allocation changed")

        def recheck():
            state.rechecked = True
            if "recheck" in state.faults:
                raise ValueError("original allocation changed")

        return SimpleNamespace(
            request=SimpleNamespace(purpose=state.purpose), assert_current=recheck
        )

    def opened(path, flags):
        assert flags & selection.os.O_NOFOLLOW and flags & selection.os.O_CLOEXEC
        return 23

    state.execute = Mock(side_effect=Delegated)
    state.closed = Mock()
    monkeypatch.setattr(selection, "_ROOT", PinnedPath())
    monkeypatch.setattr(selection, "read_embedding_batch_control", read_control)
    monkeypatch.setattr(
        selection,
        "os",
        SimpleNamespace(
            environ={
                selection._RELEASE_ENV: OLD,
                selection._HASH_ENV: "sha256:" + hashlib.sha256(RAW).hexdigest(),
            },
            getresuid=lambda: (0, 0, 0),
            getresgid=lambda: (0, 0, 0),
            open=opened,
            fstat=lambda fd: leaf,
            read=lambda fd, maximum: RAW,
            execve=state.execute,
            close=state.closed,
            O_RDONLY=0,
            O_CLOEXEC=0x80000,
            O_NOFOLLOW=0x20000,
        ),
    )
    monkeypatch.setattr(
        selection,
        "sys",
        SimpleNamespace(
            executable=selection._PYTHON,
            flags=SimpleNamespace(isolated=1),
            dont_write_bytecode=True,
        ),
    )
    state.leaf = leaf
    return state


def test_index_executes_only_root_pinned_original_controller_and_rechecks_original_allocation(
    ports,
):
    with pytest.raises(Delegated):
        selection.delegate_pinned_index_controller(ATTEMPT, current_release=CURRENT)
    assert ports.rechecked
    path = f"/opt/eom/embedding-owner-releases/{OLD}/prepare_native_index.py"
    ports.execute.assert_called_once_with(
        selection._PYTHON,
        (selection._PYTHON, "-I", "-B", path, "GPU_BATCH", ATTEMPT),
        dict(selection.os.environ),
    )
    ports.closed.assert_called_once_with(23)


@pytest.mark.parametrize("purpose", ["REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"])
def test_query_never_delegates_to_index_controller(ports, purpose):
    ports.purpose = purpose
    selection.delegate_pinned_index_controller(ATTEMPT, current_release=CURRENT)
    ports.execute.assert_not_called()
    ports.closed.assert_not_called()


def test_absent_pin_pair_preserves_single_release_installation(ports, monkeypatch):
    selection.os.environ.clear()
    reader = Mock(side_effect=AssertionError("old installation must not change"))
    monkeypatch.setattr(selection, "read_embedding_batch_control", reader)
    selection.delegate_pinned_index_controller(ATTEMPT, current_release=CURRENT)
    reader.assert_not_called()


def test_same_release_does_not_exec_itself(ports):
    selection.delegate_pinned_index_controller(ATTEMPT, current_release=OLD)
    ports.execute.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "parent",
        "path",
        "allocation",
        "recheck",
        "hash",
        "owner",
        "mode",
        "link",
        "size",
        "symlink",
        "partial",
        "uid",
        "interpreter",
        "release",
    ],
)
def test_invalid_binding_never_executes_any_controller(ports, fault):
    ports.faults.add(fault)
    if fault in {"owner", "mode", "link", "size", "symlink"}:
        name, value = {
            "owner": ("st_uid", 1000),
            "mode": ("st_mode", stat.S_IFREG | 0o666),
            "link": ("st_nlink", 2),
            "size": ("st_size", 65537),
            "symlink": ("st_mode", stat.S_IFLNK | 0o777),
        }[fault]
        setattr(ports.leaf, name, value)
    if fault == "hash":
        selection.os.environ[selection._HASH_ENV] = "sha256:" + "0" * 64
    if fault == "partial":
        del selection.os.environ[selection._HASH_ENV]
    if fault == "uid":
        selection.os.getresuid = lambda: (1000, 1000, 1000)
    if fault == "interpreter":
        selection.sys.executable = "/usr/bin/python3"
    if fault == "release":
        selection.os.environ[selection._RELEASE_ENV] = "../../not-code"
    with pytest.raises(ValueError):
        selection.delegate_pinned_index_controller(ATTEMPT, current_release=CURRENT)
    ports.execute.assert_not_called()
