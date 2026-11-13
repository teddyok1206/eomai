"""Bounded native exam ZIP inventory; never extracts or registers user content."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from collections import defaultdict
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from eom_catalog_contracts.native_exam_intake import (
    NativeExamArchiveInventory,
    NativeExamArchiveMember,
    NativeExamFolder,
)
from pydantic import ValidationError

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2000
_OLE = bytes.fromhex("d0cf11e0a1b11ae1")


class NativeExamArchiveError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "NATIVE_EXAM_ARCHIVE_" + code
        super().__init__(self.code)


def _identity(s: os.stat_result) -> tuple[int, ...]:
    return (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_nlink, s.st_mtime_ns, s.st_ctime_ns)


def native_exam_member_name(info: ZipInfo) -> str:
    """Repair reversible unflagged UTF-8 only; the untouched ZIP name is kept separately."""
    name = info.filename
    if not info.flag_bits & 0x800:
        with suppress(UnicodeError):
            name = name.encode("cp437").decode("utf-8")
    name = unicodedata.normalize("NFC", name)
    checked = name[:-1] if name.endswith("/") else name
    if (
        not checked
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(part in {"", ".", ".."} for part in checked.split("/"))
        or len(name) > 2048
    ):
        raise NativeExamArchiveError("PATH_INVALID")
    return name


def _safe_members(archive: ZipFile) -> tuple[tuple[ZipInfo, str], ...]:
    infos = archive.infolist()
    if not 1 <= len(infos) <= MAX_ARCHIVE_MEMBERS:
        raise NativeExamArchiveError("LIMIT")
    total = 0
    seen: set[str] = set()
    result = []
    for info in infos:
        name = native_exam_member_name(info)
        key = name.rstrip("/").casefold()
        if key in seen:
            raise NativeExamArchiveError("NAME_COLLISION")
        seen.add(key)
        if (
            info.flag_bits & 1
            or stat.S_ISLNK(info.external_attr >> 16)
            or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or not 0 <= info.file_size <= MAX_MEMBER_BYTES
            or info.file_size > max(1, info.compress_size) * 1000
        ):
            raise NativeExamArchiveError("MEMBER_INVALID")
        mode = stat.S_IFMT(info.external_attr >> 16)
        if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise NativeExamArchiveError("MEMBER_INVALID")
        total += info.file_size
        if total > MAX_EXPANDED_BYTES:
            raise NativeExamArchiveError("LIMIT")
        result.append((info, name))
    return tuple(result)


def _is_metadata(name: str) -> bool:
    return any(p == "__MACOSX" or p.startswith("._") for p in name.split("/")) or (
        PurePosixPath(name).name == ".DS_Store"
    )


def _format(
    archive: ZipFile, info: ZipInfo, name: str, prefix: bytes
) -> Literal["HWP", "HWPX", "XLSX"]:
    suffix = PurePosixPath(name).suffix.casefold()
    if suffix not in {".hwp", ".hwpx", ".xlsx"}:
        raise NativeExamArchiveError("PAYLOAD_UNSUPPORTED")
    if suffix != ".xlsx" and prefix.startswith(_OLE):
        return "HWP"
    if not prefix.startswith(b"PK\x03\x04"):
        raise NativeExamArchiveError("SOURCE_FORMAT_INVALID")
    with archive.open(info) as source, ZipFile(source) as package:
        members = _safe_members(package)
        names = {n for _, n in members}
        if suffix == ".xlsx":
            if not {"[Content_Types].xml", "xl/workbook.xml"} <= names:
                raise NativeExamArchiveError("SOURCE_FORMAT_INVALID")
            return "XLSX"
        if not {"mimetype", "Contents/content.hpf"} <= names:
            raise NativeExamArchiveError("SOURCE_FORMAT_INVALID")
        if package.getinfo("mimetype").file_size > 100:
            raise NativeExamArchiveError("SOURCE_FORMAT_INVALID")
        if package.read("mimetype") != b"application/hwp+zip":
            raise NativeExamArchiveError("SOURCE_FORMAT_INVALID")
        return "HWPX"


def _member(archive: ZipFile, info: ZipInfo, name: str) -> NativeExamArchiveMember:
    digest = hashlib.sha256()
    total = 0
    prefix = b""
    with archive.open(info) as source:
        while chunk := source.read(1024 * 1024):
            if not prefix:
                prefix = chunk[:16]
            total += len(chunk)
            if total > info.file_size or total > MAX_MEMBER_BYTES:
                raise NativeExamArchiveError("MEMBER_INVALID")
            digest.update(chunk)
    if total != info.file_size or total < 8:
        raise NativeExamArchiveError("MEMBER_INVALID")
    return NativeExamArchiveMember(
        zip_member=info.filename,
        member_path=name,
        source_format=_format(archive, info, name, prefix),
        sha256="sha256:" + digest.hexdigest(),
        bytes=total,
    )


def _role(member: NativeExamArchiveMember) -> str:
    if member.source_format == "XLSX":
        return "workbook"
    stem = PurePosixPath(member.member_path).stem.casefold()
    question = any(s in stem for s in ("문제지", "시험지", "question"))
    solutions = any(s in stem for s in ("해설", "solution"))
    if question == solutions:
        raise NativeExamArchiveError("SOURCE_ROLE_AMBIGUOUS")
    return "question" if question else "solutions"


def _inventory(stream: BinaryIO, sha256: str, size: int) -> NativeExamArchiveInventory:
    groups: dict[str, dict[str, NativeExamArchiveMember]] = defaultdict(dict)
    ignored = 0
    with ZipFile(stream) as archive:
        for info, name in _safe_members(archive):
            if info.is_dir():
                continue
            if _is_metadata(name):
                ignored += 1
                continue
            folder = str(PurePosixPath(name).parent)
            if folder == ".":
                raise NativeExamArchiveError("FOLDER_REQUIRED")
            if len(groups) >= 128 and folder not in groups:
                raise NativeExamArchiveError("LIMIT")
            member = _member(archive, info, name)
            role = _role(member)
            if role in groups[folder]:
                raise NativeExamArchiveError("SOURCE_ROLE_AMBIGUOUS")
            groups[folder][role] = member
    folders = []
    for folder, members in sorted(groups.items()):
        if not {"question", "solutions"} <= members.keys():
            raise NativeExamArchiveError("SOURCE_PAIR_INCOMPLETE")
        folders.append(
            NativeExamFolder(
                folder_path=folder,
                question=members["question"],
                solutions=members["solutions"],
                workbook=members.get("workbook"),
            )
        )
    if not folders:
        raise NativeExamArchiveError("EMPTY")
    return NativeExamArchiveInventory(
        sha256=sha256,
        bytes=size,
        folders=tuple(folders),
        ignored_metadata_count=ignored,
    )


def read_native_exam_archive(path: Path) -> NativeExamArchiveInventory:
    """Hash bounded regular source and each member, leaving bytes in their original ZIP."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 8 <= before.st_size <= MAX_ARCHIVE_BYTES
            ):
                raise NativeExamArchiveError("FILE_INVALID")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            stream.seek(0)
            result = _inventory(stream, "sha256:" + digest, before.st_size)
            if _identity(before) != _identity(os.fstat(stream.fileno())) or (
                _identity(before) != _identity(path.lstat())
            ):
                raise NativeExamArchiveError("FILE_CHANGED")
            return result
    except NativeExamArchiveError:
        raise
    except (OSError, BadZipFile, ValueError, KeyError, RuntimeError, ValidationError) as exc:
        raise NativeExamArchiveError("PACKAGE_INVALID") from exc
