"""Read-only attestation for the reviewed content-team HwpQuestionEditor handoff ZIP."""

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final

HANDOFF_ARCHIVE_SHA256: Final = (
    "sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91"
)
MAX_ARCHIVE_BYTES: Final = 64 * 1024 * 1024
MAX_ENTRY_COUNT: Final = 1000
MAX_MEMBER_BYTES: Final = 25 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED: Final = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO: Final = 100

EXPECTED_MEMBER_HASHES: Mapping[str, str] = MappingProxyType(
    {
        "automation-template": (
            "sha256:22ded5c8de95a8c9659544749fd21a109f40a1c7b5963e123887c0d9ca51a687"
        ),
        "equation-prototypes": (
            "sha256:2a493d5e90f1d80cb28805f2f9fecf9c18853cbc0521d7acc7a64cc249c1c45a"
        ),
        "visual-slots-left-right": (
            "sha256:65674a863762e29230bab2010b6a38e52a1f44d50cb6b0509c1205ce44c4c593"
        ),
        "visual-slots-two-tables": (
            "sha256:3d5f54f3915d071d978f05037dffc03cec7385a87cb5a16fa460414f43cbbb13"
        ),
        "labeled-data-condition": (
            "sha256:cf517788ed36fe388e2580a1455dc5e343fcb68aeca5e007194180aafbf91e76"
        ),
        "table-2-column": (
            "sha256:d29e2891481554869540dfd3c62f5217cd589b3bb3197f89b3126ced9f8332eb"
        ),
        "table-3-column": (
            "sha256:9812ab156524e34f51d10123a0a8bb7991947cba95e960da1a03b5fdb5d5d3b9"
        ),
        "table-3-column-long-equation": (
            "sha256:5521c89d0772e59a963994db09c946e6407ca2664c51de7e738033645e192335"
        ),
        "table-4-column": (
            "sha256:dae3a87c48c36bc3fdaf4efd3e746f7a9d00f70217876a700e320cafc110e9d9"
        ),
        "inquiry-experiment-box": (
            "sha256:b11841cbc812f6d0179d8ce59fb2d0d4c60706445b12e03726d5819e35f70d6f"
        ),
    }
)


class ContentTeamHandoffError(ValueError):
    """The external handoff does not match the reviewed immutable profile."""


@dataclass(frozen=True)
class _ArchiveIdentity:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True)
class HandoffMemberEvidence:
    purpose: str
    archive_member: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ContentTeamHandoffEvidence:
    archive_sha256: str
    entry_count: int
    uncompressed_bytes: int
    members: tuple[HandoffMemberEvidence, ...]


def _identity(metadata: os.stat_result) -> _ArchiveIdentity:
    return _ArchiveIdentity(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=metadata.st_mode,
        links=metadata.st_nlink,
        size=metadata.st_size,
        modified_ns=metadata.st_mtime_ns,
        changed_ns=metadata.st_ctime_ns,
    )


def _hash_fd(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_archive_fd(path: Path, expected_sha256: str) -> tuple[int, _ArchiveIdentity]:
    fd: int | None = None
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_ARCHIVE_BYTES
        ):
            raise OSError("unsafe handoff archive")
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        after = os.fstat(fd)
        identity = _identity(after)
        if _identity(before) != identity:
            raise OSError("handoff archive identity changed")
        if _hash_fd(fd) != expected_sha256:
            raise OSError("handoff archive hash mismatch")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd, identity
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        raise ContentTeamHandoffError("content-team handoff archive is unsafe") from exc


def _hash_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    size = 0
    with archive.open(info, "r") as member:
        while chunk := member.read(1024 * 1024):
            size += len(chunk)
            if size > info.file_size or size > MAX_MEMBER_BYTES:
                raise ContentTeamHandoffError("content-team handoff member size changed")
            digest.update(chunk)
    if size != info.file_size:
        raise ContentTeamHandoffError("content-team handoff member size changed")
    return f"sha256:{digest.hexdigest()}"


def _safe_member_name(name: str) -> None:
    relative = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or relative.is_absolute()
        or "." in relative.parts
        or ".." in relative.parts
        or relative.as_posix() != name.rstrip("/")
    ):
        raise ContentTeamHandoffError("content-team handoff member path is unsafe")


def inspect_content_team_handoff(
    path: Path,
    *,
    expected_archive_sha256: str = HANDOFF_ARCHIVE_SHA256,
    expected_member_hashes: Mapping[str, str] = EXPECTED_MEMBER_HASHES,
) -> ContentTeamHandoffEvidence:
    """Attest required binaries without extracting or executing any handoff member."""

    fd, archive_identity = _read_archive_fd(path, expected_archive_sha256)
    try:
        with (
            os.fdopen(os.dup(fd), "rb", closefd=True) as stream,
            zipfile.ZipFile(stream) as archive,
        ):
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ENTRY_COUNT:
                raise ContentTeamHandoffError("content-team handoff entry count is unsafe")
            names: set[str] = set()
            casefolded: set[str] = set()
            total = 0
            candidates: dict[str, list[HandoffMemberEvidence]] = {
                digest: [] for digest in expected_member_hashes.values()
            }
            purpose_by_hash = {
                digest: purpose for purpose, digest in expected_member_hashes.items()
            }
            if len(purpose_by_hash) != len(expected_member_hashes):
                raise ContentTeamHandoffError("content-team handoff profile hashes are not unique")
            for info in infos:
                _safe_member_name(info.filename)
                folded = info.filename.casefold()
                if info.filename in names or folded in casefolded:
                    raise ContentTeamHandoffError("content-team handoff has duplicate member names")
                names.add(info.filename)
                casefolded.add(folded)
                mode = info.external_attr >> 16
                if info.flag_bits & 0x1 or stat.S_ISLNK(mode):
                    raise ContentTeamHandoffError(
                        "content-team handoff member is encrypted or linked"
                    )
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ContentTeamHandoffError(
                        "content-team handoff member exceeds its size limit"
                    )
                total += info.file_size
                if (
                    total > MAX_TOTAL_UNCOMPRESSED
                    or info.file_size > max(info.compress_size, 1) * MAX_COMPRESSION_RATIO
                ):
                    raise ContentTeamHandoffError("content-team handoff has unsafe compression")
                if info.is_dir() or not info.filename.endswith(".hwpx"):
                    continue
                tagged = _hash_member(archive, info)
                purpose = purpose_by_hash.get(tagged)
                if purpose is not None:
                    candidates[tagged].append(
                        HandoffMemberEvidence(purpose, info.filename, tagged, info.file_size)
                    )
            members: list[HandoffMemberEvidence] = []
            for purpose, digest in expected_member_hashes.items():
                matches = candidates[digest]
                if len(matches) != 1 or matches[0].purpose != purpose:
                    raise ContentTeamHandoffError(
                        "content-team handoff required member is missing or ambiguous"
                    )
                members.append(matches[0])
            if _identity(os.fstat(fd)) != archive_identity:
                raise ContentTeamHandoffError("content-team handoff archive identity changed")
            if _hash_fd(fd) != expected_archive_sha256:
                raise ContentTeamHandoffError("content-team handoff archive changed while reading")
            if _identity(os.fstat(fd)) != archive_identity:
                raise ContentTeamHandoffError("content-team handoff archive identity changed")
            return ContentTeamHandoffEvidence(
                archive_sha256=expected_archive_sha256,
                entry_count=len(infos),
                uncompressed_bytes=total,
                members=tuple(members),
            )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ContentTeamHandoffError("content-team handoff ZIP structure is invalid") from exc
    finally:
        os.close(fd)
