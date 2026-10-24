"""Kernel credential/birth parsing; root-owned /proc metadata is not process authority."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_batch_owner_identity as identity


def test_real_current_kernel_identity_and_mismatched_credentials():
    assert (
        identity.embedding_batch_owner_start_ticks(os.getpid(), uid=os.getuid(), gid=os.getgid())
        > 0
    )
    with pytest.raises(ValueError):
        identity.embedding_batch_owner_start_ticks(
            os.getpid(), uid=os.getuid() + 1, gid=os.getgid()
        )


@pytest.mark.parametrize(
    "pid,uid,gid", ((False, 1, 1), (0, 1, 1), (2**31, 1, 1), (1, True, 1), (1, -1, 1), (1, 1, 1.0))
)
def test_invalid_identity_numbers_are_not_kernel_lookups(pid, uid, gid):
    with pytest.raises(ValueError):
        identity.embedding_batch_owner_start_ticks(pid, uid=uid, gid=gid)


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "saved_root",
        "effective_root",
        "group",
        "duplicate",
        "foreign_owner",
        "reused",
        "zombie",
    ),
)
def test_nondumpable_metadata_requires_all_credentials_and_stable_active_birth(monkeypatch, fault):
    pid, uid, gid = os.getpid(), os.getuid(), os.getgid()
    raw_stat = Path(f"/proc/{pid}/stat").read_bytes()
    prefix, separator, rest = raw_stat.rpartition(b") ")
    values = rest.split()
    status_uid = [str(uid).encode()] * 4
    status_gid = [str(gid).encode()] * 4
    if fault == "saved_root":
        status_uid[2] = b"0"
    elif fault == "effective_root":
        status_uid[1] = b"0"
    elif fault == "group":
        status_gid[1] = str(gid + 1).encode()
    if fault == "zombie":
        values[0] = b"Z"
    raw_stat = prefix + separator + b" ".join(values)
    changed = values.copy()
    changed[19] = str(int(changed[19]) + 1).encode()
    reused = prefix + separator + b" ".join(changed)
    raw_status = b"Uid:\t" + b"\t".join(status_uid) + b"\nGid:\t" + b"\t".join(status_gid) + b"\n"
    if fault == "duplicate":
        raw_status += b"Uid:\t" + b"\t".join(status_uid) + b"\n"

    class ProcMetadataPath(type(Path())):
        def lstat(self):
            return SimpleNamespace(st_uid=uid + 10 if fault == "foreign_owner" else 0)

    calls = []

    def read(path, *, maximum, owner_uid, leaf_owner_uid):
        assert owner_uid == uid and leaf_owner_uid == 0
        calls.append(path.name)
        if path.name == "status":
            return raw_status
        return reused if fault == "reused" and calls.count("stat") == 2 else raw_stat

    monkeypatch.setattr(identity, "Path", ProcMetadataPath)
    monkeypatch.setattr(identity, "read_live_runtime_os_file", read)
    if fault is None:
        assert identity.embedding_batch_owner_start_ticks(pid, uid=uid, gid=gid) == int(values[19])
        assert calls == ["stat", "status", "stat"]
    else:
        with pytest.raises(ValueError):
            identity.embedding_batch_owner_start_ticks(pid, uid=uid, gid=gid)
