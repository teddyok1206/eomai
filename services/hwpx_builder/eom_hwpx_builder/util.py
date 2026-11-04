"""Deterministic serialization and hashing local to the isolated builder."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def read_stable_local_file(path: Path, *, max_bytes: int) -> bytes:
    """Bound one explicit local input read and reject symlinks or a changing file."""
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= max_bytes:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "local input metadata is invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(max_bytes + 1)
        after = os.fstat(descriptor)

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after) or len(data) != before.st_size:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "local input changed during read")
        return data
    finally:
        os.close(descriptor)


def write_json(path: Path, value: Any) -> None:
    data = canonical_json_bytes(value) + b"\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
