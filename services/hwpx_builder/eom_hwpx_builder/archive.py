"""Bounded, traversal-safe HWPX ZIP handling."""

from __future__ import annotations

import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import EntryRecord, PackageLimits
from eom_hwpx_builder.util import sha256_bytes, sha256_file

FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class PackageEntry:
    info: zipfile.ZipInfo
    data: bytes


@dataclass(frozen=True)
class SafePackage:
    path: Path
    package_sha256: str
    entries: tuple[PackageEntry, ...]

    def by_name(self) -> dict[str, PackageEntry]:
        return {entry.info.filename: entry for entry in self.entries}

    def records(self) -> tuple[EntryRecord, ...]:
        return tuple(
            EntryRecord(
                name=entry.info.filename,
                order=index,
                compression_method=entry.info.compress_type,
                compressed_size=entry.info.compress_size,
                uncompressed_size=entry.info.file_size,
                crc=entry.info.CRC,
                sha256=sha256_bytes(entry.data),
                is_xml=entry.info.filename.lower().endswith((".xml", ".hpf")),
            )
            for index, entry in enumerate(self.entries)
        )


def _validate_name(name: str, limits: PackageLimits) -> None:
    if not name or "\x00" in name or len(name) > limits.max_filename_length:
        raise HwpxError(HwpxErrorCode.HWPX_ZIP_PATH_TRAVERSAL, "unsafe archive entry name")
    if "\\" in name:
        raise HwpxError(HwpxErrorCode.HWPX_ZIP_PATH_TRAVERSAL, "backslash path rejected")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or name.startswith("/"):
        raise HwpxError(HwpxErrorCode.HWPX_ZIP_PATH_TRAVERSAL, "archive path escaped root")


def read_package(path: Path, limits: PackageLimits | None = None) -> SafePackage:
    actual_limits = limits or PackageLimits()
    try:
        if path.stat().st_size > actual_limits.max_package_bytes:
            raise HwpxError(HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED, "package size limit exceeded")
    except OSError as exc:
        raise HwpxError(HwpxErrorCode.HWPX_ZIP_INVALID, "package is unavailable") from exc
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise HwpxError(HwpxErrorCode.HWPX_ZIP_INVALID, "invalid ZIP package") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > actual_limits.max_entries:
            raise HwpxError(HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED, "entry count limit exceeded")
        names: set[str] = set()
        folded: set[str] = set()
        total = 0
        entries: list[PackageEntry] = []
        for info in infos:
            _validate_name(info.filename, actual_limits)
            if info.filename in names or info.filename.casefold() in folded:
                raise HwpxError(
                    HwpxErrorCode.HWPX_ZIP_DUPLICATE_ENTRY,
                    "duplicate or case-colliding archive entry",
                )
            names.add(info.filename)
            folded.add(info.filename.casefold())
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR} or stat.S_ISLNK(mode):
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "special entry rejected")
            if info.file_size > actual_limits.max_member_bytes:
                raise HwpxError(HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED, "member size limit exceeded")
            total += info.file_size
            if total > actual_limits.max_uncompressed_bytes:
                raise HwpxError(
                    HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED,
                    "uncompressed package size limit exceeded",
                )
            ratio = info.file_size / max(info.compress_size, 1)
            if info.file_size > 1024 and ratio > actual_limits.max_compression_ratio:
                raise HwpxError(
                    HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED,
                    "compression ratio limit exceeded",
                )
            if info.is_dir():
                data = b""
            else:
                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_ZIP_INVALID, "archive member read failed"
                    ) from exc
            entries.append(PackageEntry(info=info, data=data))
    return SafePackage(path=path, package_sha256=sha256_file(path), entries=tuple(entries))


def extract_package(package: SafePackage, destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = destination.resolve()
    for entry in package.entries:
        target = destination / entry.info.filename
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise HwpxError(HwpxErrorCode.HWPX_ZIP_PATH_TRAVERSAL, "extraction escaped root")
        if entry.info.is_dir():
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            continue
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            remaining = memoryview(entry.data)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("archive member write made no progress")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)


def canonicalize_package(source: Path, output: Path) -> SafePackage:
    """Rewrite a validated package with fixed timestamps and stable entry metadata."""

    package = read_package(source)
    if output.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "output package already exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "temporary output already exists")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=False) as archive:
            for entry in package.entries:
                info = zipfile.ZipInfo(entry.info.filename, FIXED_ZIP_TIMESTAMP)
                info.compress_type = entry.info.compress_type
                info.comment = entry.info.comment
                info.extra = b""
                info.internal_attr = entry.info.internal_attr
                info.external_attr = entry.info.external_attr
                info.create_system = entry.info.create_system
                archive.writestr(info, entry.data)
        temporary.chmod(0o600)
        temporary.replace(output)
    except (OSError, zipfile.BadZipFile) as exc:
        temporary.unlink(missing_ok=True)
        raise HwpxError(
            HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "canonical package write failed"
        ) from exc
    return read_package(output)
