#!/usr/bin/env python3
"""Fail-closed verifier for the standard RECORD inside release wheels."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import os
import re
import stat
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final

_EXPECTED_DISTRIBUTIONS: Final = frozenset(
    {"eom_api_contracts", "eom_application_api", "eom_platform"}
)
_MAX_WHEEL_BYTES: Final = 256 * 1024 * 1024
_MAX_MEMBER_BYTES: Final = 64 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES: Final = 512 * 1024 * 1024
_MAX_RECORD_BYTES: Final = 8 * 1024 * 1024
_MAX_MEMBERS: Final = 10_000
_SHA256_RECORD_PATTERN: Final = re.compile(r"^sha256=([A-Za-z0-9_-]{43})$")
_SIZE_PATTERN: Final = re.compile(r"^(?:0|[1-9][0-9]*)$")
_READ_BYTES: Final = 1024 * 1024


class WheelRecordError(RuntimeError):
    """A wheel or its RECORD does not describe the exact member bytes."""


@dataclass(frozen=True)
class VerifiedWheelIdentity:
    """Exact raw wheel bytes and stable file identity accepted by the verifier."""

    filename: str
    sha256: str
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _safe_member_name(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise WheelRecordError("WHEEL_RECORD_PATH_INVALID")
    return value


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[bytes, int]:
    digest = hashlib.sha256()
    size = 0
    with archive.open(info, "r") as member:
        while chunk := member.read(_READ_BYTES):
            digest.update(chunk)
            size += len(chunk)
            if size > _MAX_MEMBER_BYTES:
                raise WheelRecordError("WHEEL_RECORD_MEMBER_TOO_LARGE")
    return digest.digest(), size


def _read_bounded_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, maximum_bytes: int
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    with archive.open(info, "r") as member:
        while chunk := member.read(min(_READ_BYTES, maximum_bytes + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise WheelRecordError("WHEEL_RECORD_TOO_LARGE")
    if size != info.file_size:
        raise WheelRecordError("WHEEL_RECORD_CONTENT_MISMATCH")
    return b"".join(chunks)


def _hash_open_file(descriptor: int, expected_size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while chunk := os.pread(descriptor, _READ_BYTES, offset):
        digest.update(chunk)
        offset += len(chunk)
        if offset > _MAX_WHEEL_BYTES:
            raise WheelRecordError("WHEEL_RECORD_FILE_IDENTITY")
    if offset != expected_size:
        raise WheelRecordError("WHEEL_RECORD_FILE_CHANGED")
    return "sha256:" + digest.hexdigest()


def _verify_open_wheel(stream: BinaryIO, *, expected_distribution: str) -> None:
    with zipfile.ZipFile(stream, "r") as archive:
        if archive.comment:
            raise WheelRecordError("WHEEL_RECORD_ARCHIVE_COMMENT")
        infos = archive.infolist()
        if not 1 <= len(infos) <= _MAX_MEMBERS:
            raise WheelRecordError("WHEEL_RECORD_MEMBER_COUNT")
        names: dict[str, zipfile.ZipInfo] = {}
        total_uncompressed = 0
        for info in infos:
            if info.is_dir():
                raise WheelRecordError("WHEEL_RECORD_MEMBER_TYPE")
            name = _safe_member_name(info.filename)
            if name in names:
                raise WheelRecordError("WHEEL_RECORD_MEMBER_DUPLICATE")
            unix_mode = info.external_attr >> 16
            if unix_mode and not stat.S_ISREG(unix_mode):
                raise WheelRecordError("WHEEL_RECORD_MEMBER_TYPE")
            if info.flag_bits & 0x1:
                raise WheelRecordError("WHEEL_RECORD_MEMBER_ENCRYPTED")
            if info.file_size > _MAX_MEMBER_BYTES:
                raise WheelRecordError("WHEEL_RECORD_MEMBER_TOO_LARGE")
            total_uncompressed += info.file_size
            if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise WheelRecordError("WHEEL_RECORD_ARCHIVE_TOO_LARGE")
            names[name] = info

        record_names = tuple(name for name in names if name.endswith(".dist-info/RECORD"))
        if len(record_names) != 1:
            raise WheelRecordError("WHEEL_RECORD_IDENTITY")
        record_name = record_names[0]
        dist_info_roots = {name.split("/", 1)[0] for name in names if ".dist-info/" in name}
        expected_prefix = f"{expected_distribution}-"
        if (
            len(dist_info_roots) != 1
            or not record_name.startswith(expected_prefix)
            or record_name.split("/", 1)[0] not in dist_info_roots
        ):
            raise WheelRecordError("WHEEL_RECORD_IDENTITY")
        record_info = names[record_name]
        if record_info.file_size > _MAX_RECORD_BYTES:
            raise WheelRecordError("WHEEL_RECORD_TOO_LARGE")
        try:
            record_text = _read_bounded_member(archive, record_info, _MAX_RECORD_BYTES).decode(
                "utf-8"
            )
            rows = tuple(csv.reader(io.StringIO(record_text, newline=""), strict=True))
        except (UnicodeError, csv.Error, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise WheelRecordError("WHEEL_RECORD_PARSE_FAILED") from exc

        entries: dict[str, tuple[str, str]] = {}
        for row in rows:
            if len(row) != 3:
                raise WheelRecordError("WHEEL_RECORD_ROW_INVALID")
            name = _safe_member_name(row[0])
            if name in entries:
                raise WheelRecordError("WHEEL_RECORD_ROW_DUPLICATE")
            entries[name] = (row[1], row[2])
        if set(entries) != set(names):
            raise WheelRecordError("WHEEL_RECORD_PATH_SET_MISMATCH")

        for name, info in names.items():
            declared_hash, declared_size = entries[name]
            if name == record_name:
                if declared_hash or declared_size:
                    raise WheelRecordError("WHEEL_RECORD_SELF_RULE")
                continue
            match = _SHA256_RECORD_PATTERN.fullmatch(declared_hash)
            if (
                match is None
                or len(declared_size) > 20
                or _SIZE_PATTERN.fullmatch(declared_size) is None
            ):
                raise WheelRecordError("WHEEL_RECORD_DIGEST_OR_SIZE_INVALID")
            encoded_digest = match.group(1)
            try:
                decoded_digest = base64.urlsafe_b64decode(encoded_digest + "=")
            except binascii.Error as exc:
                raise WheelRecordError("WHEEL_RECORD_DIGEST_INVALID") from exc
            canonical_digest = base64.urlsafe_b64encode(decoded_digest).rstrip(b"=").decode("ascii")
            if len(decoded_digest) != 32 or canonical_digest != encoded_digest:
                raise WheelRecordError("WHEEL_RECORD_DIGEST_INVALID")
            observed_digest, observed_size = _read_member(archive, info)
            if (
                not hmac.compare_digest(observed_digest, decoded_digest)
                or observed_size != int(declared_size)
                or observed_size != info.file_size
            ):
                raise WheelRecordError("WHEEL_RECORD_CONTENT_MISMATCH")


def verify_wheel_record(path: Path) -> VerifiedWheelIdentity:
    """Verify one regular, private wheel and every RECORD member binding."""

    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_gid != os.getgid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 1 <= before.st_size <= _MAX_WHEEL_BYTES
        ):
            raise WheelRecordError("WHEEL_RECORD_FILE_IDENTITY")
        expected_distribution = path.name.split("-", 1)[0]
        if expected_distribution not in _EXPECTED_DISTRIBUTIONS:
            raise WheelRecordError("WHEEL_RECORD_IDENTITY")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            _verify_open_wheel(stream, expected_distribution=expected_distribution)
        digest = _hash_open_file(descriptor, before.st_size)
        after = os.fstat(descriptor)
        if _identity(before) != _identity(after):
            raise WheelRecordError("WHEEL_RECORD_FILE_CHANGED")
        return VerifiedWheelIdentity(
            filename=path.name,
            sha256=digest,
            device=after.st_dev,
            inode=after.st_ino,
            mode=stat.S_IMODE(after.st_mode),
            uid=after.st_uid,
            gid=after.st_gid,
            nlink=after.st_nlink,
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
            ctime_ns=after.st_ctime_ns,
        )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise WheelRecordError("WHEEL_RECORD_READ_FAILED") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def main(arguments: tuple[str, ...] | None = None) -> int:
    values = tuple(sys.argv[1:] if arguments is None else arguments)
    emit_identity = bool(values and values[0] == "--emit-identity")
    if emit_identity:
        values = values[1:]
    if len(values) != 3:
        print("release_wheel_record_verification=INVALID_ARGUMENTS", file=sys.stderr)
        return 2
    paths = tuple(Path(value) for value in values)
    distributions = {path.name.split("-", 1)[0] for path in paths}
    if distributions != _EXPECTED_DISTRIBUTIONS or len({str(path) for path in paths}) != 3:
        print("release_wheel_record_verification=INVALID_WHEEL_SET", file=sys.stderr)
        return 2
    try:
        identities = tuple(verify_wheel_record(path) for path in sorted(paths))
    except WheelRecordError as exc:
        print(f"release_wheel_record_verification={exc}", file=sys.stderr)
        return 1
    if emit_identity:
        payload = {
            "schema_version": "release-wheel-inspection-identity/1.0",
            "wheels": [asdict(identity) for identity in identities],
        }
        print(
            "release_wheel_inspection_identity="
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
    else:
        print("release_wheel_record_verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
