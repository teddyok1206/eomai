"""Keep a running INDEX's exact controller while selecting a QUERY-only successor."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
from pathlib import Path

from eom_catalog_service.embedding_batch_control_workspace import read_embedding_batch_control

_ROOT = Path("/opt/eom/embedding-owner-releases")
_PYTHON = "/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12"
_RELEASE_ENV = "EOM_GPU_BATCH_PINNED_INDEX_CONTROLLER_RELEASE"
_HASH_ENV = "EOM_GPU_BATCH_PINNED_INDEX_BOOTSTRAP_SHA256"


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def delegate_pinned_index_controller(attempt_hex: str, *, current_release: str) -> None:
    """Root-configured code pin only; allocation input cannot choose code or a path.

    No authority is transferred: the original bootstrap independently admits the
    original peer, allocation, policy and lease. An absent pair preserves the old
    single-release installation. QUERY always stays in the current release.
    """
    release, digest = os.environ.get(_RELEASE_ENV), os.environ.get(_HASH_ENV)
    if release is None and digest is None:
        return
    if (
        os.getresuid() != (0, 0, 0)
        or os.getresgid() != (0, 0, 0)
        or sys.executable != _PYTHON
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
        or type(release) is not str
        or re.fullmatch(r"[0-9a-f]{40}", release, re.ASCII) is None
        or type(digest) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest, re.ASCII) is None
        or re.fullmatch(r"[0-9a-f]{40}", current_release, re.ASCII) is None
    ):
        raise ValueError("EMBEDDING_INDEX_CONTROLLER_SELECTION_INVALID")
    staged = read_embedding_batch_control(attempt_hex)
    if staged.request.purpose != "INDEX" or release == current_release:
        return
    path = _ROOT / release / "prepare_native_index.py"
    for parent in path.parents:
        value = parent.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise ValueError("EMBEDDING_INDEX_CONTROLLER_SELECTION_INVALID")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_mode & 0o022
            or before.st_nlink != 1
            or not 0 < before.st_size <= 64 * 1024
        ):
            raise ValueError("EMBEDDING_INDEX_CONTROLLER_SELECTION_INVALID")
        raw = os.read(descriptor, 64 * 1024 + 1)
        if (
            len(raw) != before.st_size
            or "sha256:" + hashlib.sha256(raw).hexdigest() != digest
            or _epoch(os.fstat(descriptor)) != _epoch(before)
            or _epoch(path.lstat()) != _epoch(before)
        ):
            raise ValueError("EMBEDDING_INDEX_CONTROLLER_SELECTION_INVALID")
        staged.assert_current()
        os.execve(
            _PYTHON, (_PYTHON, "-I", "-B", str(path), "GPU_BATCH", attempt_hex), dict(os.environ)
        )
    finally:
        os.close(descriptor)
