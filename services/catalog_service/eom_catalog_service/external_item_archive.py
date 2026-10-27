"""Read-only, bounded inventory of document members in an untrusted archive.

The ZIP is a transport envelope, not a Catalog Artifact. Only a later Intake
application use case may materialize and commit validated member bytes.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

_MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 30000
_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
_MAX_DOCUMENT_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_ZIP_MAGIC = b"PK\x03\x04"
_DOCUMENT_NUMBER = re.compile(r"_([0-9]{5})\.(hwp|hwpx)$", re.IGNORECASE)
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


class ExternalItemArchiveError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalItemDocumentMember:
    member_name: str
    display_filename: str
    external_number: str
    declared_format: str
    detected_format: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ExternalItemArchiveInventory:
    archive_sha256: str
    archive_size_bytes: int
    total_member_count: int
    skipped_member_count: int
    documents: tuple[ExternalItemDocumentMember, ...]


def inspect_external_item_archive(
    path: Path, *, expected_sha256: str | None = None
) -> ExternalItemArchiveInventory:
    """Hash the envelope and listed HWP/HWPX documents without extracting it."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= _MAX_ARCHIVE_BYTES
            ):
                raise ExternalItemArchiveError(
                    "EXTERNAL_ITEM_ARCHIVE_FILE_INVALID", "archive is not a bounded regular file"
                )
            digest = hashlib.sha256()
            while chunk := source.read(_CHUNK_BYTES):
                digest.update(chunk)
            archive_sha256 = "sha256:" + digest.hexdigest()
            if expected_sha256 is not None and archive_sha256 != expected_sha256:
                raise ExternalItemArchiveError(
                    "EXTERNAL_ITEM_ARCHIVE_HASH_MISMATCH", "archive identity differs"
                )
            source.seek(0)
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if not 0 < len(infos) <= _MAX_ARCHIVE_MEMBERS:
                    raise ExternalItemArchiveError(
                        "EXTERNAL_ITEM_ARCHIVE_MEMBER_LIMIT", "archive member count is invalid"
                    )
                documents = _read_documents(archive, infos)
            after = os.fstat(source.fileno())
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ExternalItemArchiveError(
                    "EXTERNAL_ITEM_ARCHIVE_FILE_CHANGED", "archive changed while reading"
                )
            return ExternalItemArchiveInventory(
                archive_sha256=archive_sha256,
                archive_size_bytes=before.st_size,
                total_member_count=len(infos),
                skipped_member_count=len(infos) - len(documents),
                documents=documents,
            )
    except OSError as exc:
        raise ExternalItemArchiveError(
            "EXTERNAL_ITEM_ARCHIVE_FILE_INVALID", "archive is unavailable"
        ) from exc
    except (zipfile.BadZipFile, EOFError, RuntimeError) as exc:
        raise ExternalItemArchiveError(
            "EXTERNAL_ITEM_ARCHIVE_PACKAGE_INVALID", "archive package is invalid"
        ) from exc


def _read_documents(
    archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
) -> tuple[ExternalItemDocumentMember, ...]:
    documents: list[ExternalItemDocumentMember] = []
    seen_names: set[str] = set()
    total_bytes = 0
    for info in infos:
        name = info.filename
        if (
            info.is_dir()
            or name.startswith("__MACOSX/")
            or name.rsplit("/", 1)[-1].startswith("._")
        ):
            continue
        filename = name.rsplit("/", 1)[-1]
        match = _DOCUMENT_NUMBER.search(filename)
        if match is None:
            continue
        components = name.split("/")
        mode = info.external_attr >> 16
        if (
            name in seen_names
            or name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in components)
            or any(ord(character) < 32 for character in name)
            or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
            or info.flag_bits & 0x1
            or info.compress_type not in _ALLOWED_COMPRESSION
            or not 0 < info.file_size <= _MAX_DOCUMENT_BYTES
        ):
            raise ExternalItemArchiveError(
                "EXTERNAL_ITEM_ARCHIVE_MEMBER_UNSAFE", "selected document member is unsafe"
            )
        seen_names.add(name)
        total_bytes += info.file_size
        if total_bytes > _MAX_DOCUMENT_TOTAL_BYTES:
            raise ExternalItemArchiveError(
                "EXTERNAL_ITEM_ARCHIVE_DOCUMENT_LIMIT", "selected documents exceed limit"
            )
        digest = hashlib.sha256()
        actual_bytes = 0
        signature = b""
        with archive.open(info, "r") as member:
            while chunk := member.read(_CHUNK_BYTES):
                if actual_bytes == 0:
                    signature = chunk[:8]
                actual_bytes += len(chunk)
                if actual_bytes > info.file_size:
                    raise ExternalItemArchiveError(
                        "EXTERNAL_ITEM_ARCHIVE_MEMBER_INVALID", "document expanded beyond metadata"
                    )
                digest.update(chunk)
        if actual_bytes != info.file_size:
            raise ExternalItemArchiveError(
                "EXTERNAL_ITEM_ARCHIVE_MEMBER_INVALID", "document length differs"
            )
        detected_format = (
            "HWP_BINARY"
            if signature == _OLE_MAGIC
            else "HWPX_PACKAGE"
            if signature.startswith(_ZIP_MAGIC)
            else "UNKNOWN"
        )
        documents.append(
            ExternalItemDocumentMember(
                member_name=name,
                display_filename=_display_filename(
                    filename, utf8_flag=bool(info.flag_bits & 0x800)
                ),
                external_number=match.group(1),
                declared_format=match.group(2).upper(),
                detected_format=detected_format,
                size_bytes=actual_bytes,
                sha256="sha256:" + digest.hexdigest(),
            )
        )
    return tuple(documents)


def _display_filename(filename: str, *, utf8_flag: bool) -> str:
    """Recover UTF-8 bytes that a ZIP producer omitted the UTF-8 filename flag for."""

    if not utf8_flag:
        try:
            recovered = filename.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        else:
            normalized = unicodedata.normalize("NFC", recovered)
            if normalized.isascii() or any("\uac00" <= char <= "\ud7a3" for char in normalized):
                filename = normalized
    return unicodedata.normalize("NFC", filename)
