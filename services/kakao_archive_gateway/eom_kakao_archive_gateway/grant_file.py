"""Bounded owner-written file input, never a public grant or filesystem path API."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from eom_kakao_archive_contracts.kakao_remote import (
    GatewayLeaseGrant,
    GatewayRevocation,
    validate_remote_contract,
)

GRANT_FILE_LIMIT = 4096


class GatewayRuntimeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@contextmanager
def protected_directory(path: Path, *, allowed_uids: frozenset[int]) -> Iterator[int]:
    if not path.is_absolute() or ".." in path.parts:
        raise GatewayRuntimeError("KAKAO_GATEWAY_PATH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in allowed_uids or info.st_mode & 0o022:
                raise GatewayRuntimeError("KAKAO_GATEWAY_DIRECTORY_UNSAFE")
        yield fd
    finally:
        os.close(fd)


def read_protected(
    path: Path,
    *,
    uid: int,
    limit: int,
    allowed_uids: frozenset[int],
    allowed_modes: frozenset[int] | None = None,
    minimum_size: int = 1,
) -> bytes:
    if not 0 <= minimum_size <= limit:
        raise GatewayRuntimeError("KAKAO_GATEWAY_READ_LIMIT_INVALID")
    with protected_directory(path.parent, allowed_uids=allowed_uids) as directory:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != uid
            or before.st_mode & 0o022
            or (allowed_modes is not None and stat.S_IMODE(before.st_mode) not in allowed_modes)
            or not minimum_size <= before.st_size <= limit
        ):
            raise GatewayRuntimeError("KAKAO_GATEWAY_MEMBER_UNSAFE")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            any(getattr(before, name) != getattr(after, name) for name in fields)
            or len(raw) != before.st_size
        ):
            raise GatewayRuntimeError("KAKAO_GATEWAY_MEMBER_CHANGED")
        return raw


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise GatewayRuntimeError("KAKAO_GATEWAY_GRANT_INVALID")
        value[key] = item
    return value


def read_owner_grant(path: Path, *, owner_uid: int) -> GatewayLeaseGrant | GatewayRevocation:
    raw = read_protected(
        path,
        uid=owner_uid,
        limit=GRANT_FILE_LIMIT,
        allowed_uids=frozenset({0, owner_uid}),
        allowed_modes=frozenset({0o440, 0o640}),
    )
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
        if not isinstance(value, dict):
            raise ValueError
        if value.get("schema_version") == "kakao-remote-gateway-revocation/1.0":
            validate_remote_contract("revocation", value)
            return GatewayRevocation.model_validate(value)
        validate_remote_contract("grant", value)
        return GatewayLeaseGrant.model_validate(value)
    except (ValueError, TypeError, UnicodeError):
        raise GatewayRuntimeError("KAKAO_GATEWAY_GRANT_INVALID") from None
