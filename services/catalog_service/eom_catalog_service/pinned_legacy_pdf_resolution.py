"""Read-only resolution of the exact pinned legacy PDF source set."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts import LegacyRootAlias, LegacySourceInventoryEntry

from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryError,
    LegacySourceRootConfiguration,
)

PINNED_PDF_SOURCE_COUNT = 50
READ_CHUNK_BYTES = 64 * 1024

_ENTRY_KEY = re.compile(r"^legacyentry_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPEN_DIRECTORY = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_OPEN_FILE = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


@dataclass(frozen=True)
class ResolvedPinnedLegacyPdfSource:
    """Minimal proof that one inventory pointer resolved to its exact local bytes."""

    entry_key: str
    relative_path: str
    byte_size: int
    content_sha256: str


class PinnedLegacyPdfResolutionError(ValueError):
    """The pinned inventory authority or one of its source files did not resolve."""


def resolve_pinned_legacy_pdf_sources(
    *,
    roots: LegacySourceRootConfiguration,
    inventory_root_alias: LegacyRootAlias,
    inventory_root_configuration_sha256: str,
    entries: tuple[LegacySourceInventoryEntry, ...],
) -> tuple[ResolvedPinnedLegacyPdfSource, ...]:
    """Hash-verify exactly 50 inventory PDFs without returning their content.

    The inventory's alias and root-configuration digest are supplied separately so this boundary
    cannot silently select another configured root. Entries must retain the inventory contract's
    deterministic relative-path order.
    """

    validated = _validate_entries(entries)
    try:
        root = roots.resolve(inventory_root_alias)
        configured_identity = roots.identity_sha256(inventory_root_alias)
    except (LegacySourceInventoryError, TypeError, ValueError) as exc:
        raise PinnedLegacyPdfResolutionError(
            "pinned legacy PDF root configuration does not resolve"
        ) from exc
    if (
        root.root_alias != inventory_root_alias
        or type(inventory_root_configuration_sha256) is not str
        or _SHA256.fullmatch(inventory_root_configuration_sha256) is None
        or configured_identity != inventory_root_configuration_sha256
    ):
        raise PinnedLegacyPdfResolutionError(
            "pinned legacy PDF root configuration does not resolve"
        )

    root_descriptors: tuple[int, ...] = ()
    try:
        root_descriptors = _open_absolute_directory_chain(Path(root.absolute_path))
        root_before = tuple(_directory_identity(os.fstat(fd)) for fd in root_descriptors)
        root_fd = root_descriptors[-1]
        resolved = tuple(_resolve_entry(root_fd, entry, parts) for entry, parts in validated)
        root_after = tuple(_directory_identity(os.fstat(fd)) for fd in root_descriptors)
        if root_before != root_after:
            raise PinnedLegacyPdfResolutionError("pinned legacy PDF root changed while resolving")
        return resolved
    except PinnedLegacyPdfResolutionError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise PinnedLegacyPdfResolutionError(
            "pinned legacy PDF source bytes do not resolve"
        ) from exc
    finally:
        _close_descriptors(root_descriptors)


def _validate_entries(
    entries: tuple[LegacySourceInventoryEntry, ...],
) -> tuple[tuple[LegacySourceInventoryEntry, tuple[str, ...]], ...]:
    if type(entries) is not tuple or len(entries) != PINNED_PDF_SOURCE_COUNT:
        raise PinnedLegacyPdfResolutionError("pinned legacy PDF inventory is invalid")

    validated: list[tuple[LegacySourceInventoryEntry, tuple[str, ...]]] = []
    entry_keys: list[str] = []
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, LegacySourceInventoryEntry):
            raise PinnedLegacyPdfResolutionError("pinned legacy PDF inventory is invalid")
        parts = _safe_relative_parts(entry.relative_path)
        if (
            type(entry.entry_key) is not str
            or _ENTRY_KEY.fullmatch(entry.entry_key) is None
            or entry.file_observation != "REGULAR"
            or entry.media_type != "application/pdf"
            or type(entry.size_bytes) is not int
            or entry.size_bytes < 0
            or type(entry.content_sha256) is not str
            or _SHA256.fullmatch(entry.content_sha256) is None
        ):
            raise PinnedLegacyPdfResolutionError("pinned legacy PDF inventory is invalid")
        entry_keys.append(entry.entry_key)
        paths.append(entry.relative_path)
        validated.append((entry, parts))

    collision_paths = tuple(path.casefold() for path in paths)
    if (
        len(entry_keys) != len(set(entry_keys))
        or len(collision_paths) != len(set(collision_paths))
        or tuple(paths) != tuple(sorted(paths, key=lambda value: (value.casefold(), value)))
    ):
        raise PinnedLegacyPdfResolutionError("pinned legacy PDF inventory is invalid")
    return tuple(validated)


def _safe_relative_parts(value: str) -> tuple[str, ...]:
    if (
        type(value) is not str
        or not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or value != unicodedata.normalize("NFC", value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PinnedLegacyPdfResolutionError("pinned legacy PDF inventory is invalid")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise PinnedLegacyPdfResolutionError("pinned legacy PDF inventory is invalid")
    return parts


def _resolve_entry(
    root_fd: int,
    entry: LegacySourceInventoryEntry,
    parts: tuple[str, ...],
) -> ResolvedPinnedLegacyPdfSource:
    directory_descriptors: tuple[int, ...] = ()
    source_fd = -1
    try:
        directory_descriptors = _open_relative_directory_chain(root_fd, parts[:-1])
        directory_before = tuple(_directory_identity(os.fstat(fd)) for fd in directory_descriptors)
        parent_fd = directory_descriptors[-1]
        observed = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size != entry.size_bytes
        ):
            raise PinnedLegacyPdfResolutionError("pinned legacy PDF source bytes do not resolve")

        source_fd = os.open(parts[-1], _OPEN_FILE, dir_fd=parent_fd)
        opened = os.fstat(source_fd)
        if _file_identity(observed) != _file_identity(opened):
            raise PinnedLegacyPdfResolutionError("pinned legacy PDF source bytes do not resolve")

        digest = hashlib.sha256()
        byte_size = 0
        remaining = entry.size_bytes + 1
        while remaining and (chunk := os.read(source_fd, min(READ_CHUNK_BYTES, remaining))):
            digest.update(chunk)
            byte_size += len(chunk)
            remaining -= len(chunk)

        closed = os.fstat(source_fd)
        directory_after = tuple(_directory_identity(os.fstat(fd)) for fd in directory_descriptors)
        content_sha256 = "sha256:" + digest.hexdigest()
        if (
            _file_identity(opened) != _file_identity(closed)
            or directory_before != directory_after
            or byte_size != entry.size_bytes
            or content_sha256 != entry.content_sha256
        ):
            raise PinnedLegacyPdfResolutionError("pinned legacy PDF source bytes do not resolve")
        return ResolvedPinnedLegacyPdfSource(
            entry_key=entry.entry_key,
            relative_path=entry.relative_path,
            byte_size=byte_size,
            content_sha256=content_sha256,
        )
    except PinnedLegacyPdfResolutionError:
        raise
    except OSError as exc:
        raise PinnedLegacyPdfResolutionError(
            "pinned legacy PDF source bytes do not resolve"
        ) from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        _close_descriptors(directory_descriptors)


def _open_absolute_directory_chain(path: Path) -> tuple[int, ...]:
    if not path.is_absolute():
        raise OSError("legacy PDF root must be absolute")
    descriptors = [os.open("/", _OPEN_DIRECTORY)]
    try:
        for part in path.parts[1:]:
            descriptor = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptors[-1])
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise OSError("legacy PDF root component is not a directory")
            descriptors.append(descriptor)
        return tuple(descriptors)
    except BaseException:
        _close_descriptors(tuple(descriptors))
        raise


def _open_relative_directory_chain(root_fd: int, parts: tuple[str, ...]) -> tuple[int, ...]:
    descriptors = [os.dup(root_fd)]
    try:
        for part in parts:
            descriptor = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptors[-1])
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise OSError("legacy PDF path component is not a directory")
            descriptors.append(descriptor)
        return tuple(descriptors)
    except BaseException:
        _close_descriptors(tuple(descriptors))
        raise


def _close_descriptors(descriptors: tuple[int, ...]) -> None:
    for descriptor in reversed(descriptors):
        os.close(descriptor)


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


__all__ = [
    "PINNED_PDF_SOURCE_COUNT",
    "PinnedLegacyPdfResolutionError",
    "ResolvedPinnedLegacyPdfSource",
    "resolve_pinned_legacy_pdf_sources",
]
