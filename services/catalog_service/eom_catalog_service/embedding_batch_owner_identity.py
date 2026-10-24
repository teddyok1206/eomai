"""Kernel identity for fixed batch owner RPC, including a non-dumpable privilege-drop child."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_process_identity import native_process_start_ticks


def embedding_batch_owner_start_ticks(pid: int, *, uid: int, gid: int) -> int:
    """Observation only; callers retain actual fixed-role peer checks and original pidfd.

    Linux makes /proc entries root-owned for a non-dumpable process after a
    privilege drop. Do not enable dumpability or confuse that storage owner with
    the process's real/effective/saved/filesystem credentials. Every credential
    must still match, and the active stat parser remains strict. The existing
    native-worker/benchmark observer is deliberately unchanged.
    """
    if (
        type(pid) is not int
        or not 0 < pid < 2**31
        or any(type(value) is not int or not 0 <= value < 2**32 for value in (uid, gid))
    ):
        raise ValueError("EMBEDDING_BATCH_OWNER_IDENTITY_INVALID")
    root = Path("/proc") / str(pid)

    def read(name: str, maximum: int) -> bytes:
        path = root / name
        owner = path.lstat().st_uid
        if owner not in {0, uid}:
            raise ValueError("EMBEDDING_BATCH_OWNER_IDENTITY_INVALID")
        return read_live_runtime_os_file(path, maximum=maximum, owner_uid=uid, leaf_owner_uid=owner)

    before = native_process_start_ticks(read("stat", 64 * 1024), pid)
    fields: dict[bytes, tuple[bytes, ...]] = {}
    for row in read("status", 128 * 1024).splitlines():
        key, separator, value = row.partition(b":")
        if key in {b"Uid", b"Gid"}:
            if not separator or key in fields:
                raise ValueError("EMBEDDING_BATCH_OWNER_IDENTITY_INVALID")
            fields[key] = tuple(value.split())
    if fields != {b"Uid": (str(uid).encode(),) * 4, b"Gid": (str(gid).encode(),) * 4}:
        raise ValueError("EMBEDDING_BATCH_OWNER_IDENTITY_INVALID")
    after = native_process_start_ticks(read("stat", 64 * 1024), pid)
    if before != after:
        raise ValueError("EMBEDDING_BATCH_OWNER_IDENTITY_INVALID")
    return before
