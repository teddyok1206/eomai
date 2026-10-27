"""Bounded local materialization of hash-pinned external Item archive members.

Only Catalog's existing Intake service may subsequently commit these files.
This module neither writes to NAS nor interprets HWP/HWPX as registered Items.
"""

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from eom_catalog_contracts import validate_contract
from eom_identifiers import canonical_json_bytes

from eom_catalog_service.external_item_archive import (
    ExternalItemArchiveInventory,
    ExternalItemDocumentMember,
)

_CHUNK_BYTES = 1024 * 1024
_MAX_BATCH_FILES = 400
_MAX_BATCH_BYTES = 1024 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
_MEDIA = {
    "HWP_BINARY": "application/vnd.hancom.hwp",
    "HWPX_PACKAGE": "application/vnd.hancom.hwpx",
}


class ExternalItemStageError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StagedExternalItemDocument:
    member_name: str
    relative_path: str
    original_filename: str
    detected_format: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class StagedExternalItemBatch:
    source_directory: Path
    archive_sha256: str
    documents: tuple[StagedExternalItemDocument, ...]
    index_relative_path: str


def plan_external_item_archive_batches(
    inventory: ExternalItemArchiveInventory,
) -> tuple[tuple[ExternalItemDocumentMember, ...], ...]:
    """Deduplicate only identical (hash, filename) copies, not different U values."""

    selected: dict[tuple[str, str], ExternalItemDocumentMember] = {}
    for document in sorted(inventory.documents, key=lambda value: value.member_name):
        if document.detected_format in _MEDIA:
            selected.setdefault((document.sha256, document.display_filename), document)
    batches: list[list[ExternalItemDocumentMember]] = []
    batch_hashes: list[set[str]] = []
    batch_bytes: list[int] = []
    for document in selected.values():
        target = next(
            (
                index
                for index, batch in enumerate(batches)
                if len(batch) < _MAX_BATCH_FILES
                and batch_bytes[index] + document.size_bytes <= _MAX_BATCH_BYTES
                and document.sha256 not in batch_hashes[index]
            ),
            None,
        )
        if target is None:
            target = len(batches)
            batches.append([])
            batch_hashes.append(set())
            batch_bytes.append(0)
        batches[target].append(document)
        batch_hashes[target].add(document.sha256)
        batch_bytes[target] += document.size_bytes
    return tuple(tuple(batch) for batch in batches)


def stage_external_item_archive_batch(
    archive_path: Path,
    inventory: ExternalItemArchiveInventory,
    members: tuple[ExternalItemDocumentMember, ...],
    target_directory: Path,
) -> StagedExternalItemBatch:
    """Rehash the exact ZIP envelope and selected members into a new local workspace."""

    available = frozenset(inventory.documents)
    if (
        not members
        or len(members) > _MAX_BATCH_FILES
        or sum(member.size_bytes for member in members) > _MAX_BATCH_BYTES
        or len({member.member_name for member in members}) != len(members)
        or len({member.sha256 for member in members}) != len(members)
        or any(
            member not in available or member.detected_format not in _MEDIA for member in members
        )
    ):
        raise ExternalItemStageError("EXTERNAL_ITEM_STAGE_SELECTION_INVALID", "batch is unsafe")
    try:
        target_directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        descriptor = os.open(
            archive_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size != inventory.archive_size_bytes
                or not 0 < before.st_size <= _MAX_ARCHIVE_BYTES
            ):
                raise ExternalItemStageError(
                    "EXTERNAL_ITEM_STAGE_ARCHIVE_CHANGED", "archive identity differs"
                )
            archive_digest = hashlib.sha256()
            while chunk := source.read(_CHUNK_BYTES):
                archive_digest.update(chunk)
            if "sha256:" + archive_digest.hexdigest() != inventory.archive_sha256:
                raise ExternalItemStageError(
                    "EXTERNAL_ITEM_STAGE_ARCHIVE_CHANGED", "archive hash differs"
                )
            source.seek(0)
            staged = _stage_selected_members(source, members, target_directory)
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
                raise ExternalItemStageError(
                    "EXTERNAL_ITEM_STAGE_ARCHIVE_CHANGED", "archive changed during staging"
                )
        index_relative_path = "archive-index.json"
        index_path = target_directory / index_relative_path
        index_body = {
            "schema_version": "external-item-archive-stage-index/1.0",
            "archive_sha256": inventory.archive_sha256,
            "documents": [
                {
                    "member_name": document.member_name,
                    "relative_path": document.relative_path,
                    "original_filename": document.original_filename,
                    "detected_format": document.detected_format,
                    "media_type": document.media_type,
                    "size_bytes": document.size_bytes,
                    "sha256": document.sha256,
                }
                for document in staged
            ],
        }
        validate_contract("external-item-archive-stage-index-v1", index_body)
        index_descriptor = os.open(
            index_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(index_descriptor, "wb") as index_output:
            index_output.write(canonical_json_bytes(index_body))
        return StagedExternalItemBatch(
            source_directory=target_directory,
            archive_sha256=inventory.archive_sha256,
            documents=staged,
            index_relative_path=index_relative_path,
        )
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise ExternalItemStageError(
            "EXTERNAL_ITEM_STAGE_UNAVAILABLE", "selected archive members cannot be staged"
        ) from exc


def _stage_selected_members(
    source: BinaryIO,
    members: tuple[ExternalItemDocumentMember, ...],
    target_directory: Path,
) -> tuple[StagedExternalItemDocument, ...]:
    staged: list[StagedExternalItemDocument] = []
    with zipfile.ZipFile(source) as archive:
        for index, document in enumerate(members, start=1):
            info = archive.getinfo(document.member_name)
            if info.file_size != document.size_bytes:
                raise ExternalItemStageError(
                    "EXTERNAL_ITEM_STAGE_MEMBER_CHANGED", "member size differs"
                )
            suffix = ".hwpx" if document.detected_format == "HWPX_PACKAGE" else ".hwp"
            relative_path = f"document-{index:04d}-{document.sha256[7:23]}{suffix}"
            target = target_directory / relative_path
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            digest = hashlib.sha256()
            count = 0
            with os.fdopen(descriptor, "wb") as output, archive.open(info, "r") as member:
                while chunk := member.read(_CHUNK_BYTES):
                    count += len(chunk)
                    if count > document.size_bytes:
                        raise ExternalItemStageError(
                            "EXTERNAL_ITEM_STAGE_MEMBER_CHANGED", "member expanded unexpectedly"
                        )
                    digest.update(chunk)
                    output.write(chunk)
            if count != document.size_bytes or "sha256:" + digest.hexdigest() != document.sha256:
                raise ExternalItemStageError(
                    "EXTERNAL_ITEM_STAGE_MEMBER_CHANGED", "member hash differs"
                )
            staged.append(
                StagedExternalItemDocument(
                    member_name=document.member_name,
                    relative_path=relative_path,
                    original_filename=document.display_filename,
                    detected_format=document.detected_format,
                    media_type=_MEDIA[document.detected_format],
                    size_bytes=count,
                    sha256=document.sha256,
                )
            )
    return tuple(staged)
