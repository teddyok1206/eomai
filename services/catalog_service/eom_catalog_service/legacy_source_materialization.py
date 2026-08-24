"""Fd-relative materialization of reviewed legacy inventory entries."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from eom_catalog_contracts import LegacyKnowledgeContractErrorCode, LegacyRootAlias
from eom_content_intake import IntakeError

from eom_catalog_service.intake_files import DiscoveredSource, discover_source_files
from eom_catalog_service.intake_service import IntakeSourceDeclaration
from eom_catalog_service.legacy_source_inventory import LegacySourceRootConfiguration
from eom_catalog_service.legacy_source_selection_boundary import (
    LegacySourceSelectionError,
    MaterializedLegacySelection,
    SelectedInventoryEntry,
)
from eom_catalog_service.settings import CatalogSettings

READ_CHUNK_BYTES = 1024 * 1024
_OPEN_READ = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_OPEN_DIRECTORY = _OPEN_READ | getattr(os, "O_DIRECTORY", 0)
_OPEN_WRITE_EXCLUSIVE = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


class LegacySourceMaterializer:
    """Create one disposable, hash-verified Content Intake source directory."""

    def __init__(self, settings: CatalogSettings) -> None:
        self.settings = settings

    @contextmanager
    def materialize(
        self,
        entries: tuple[SelectedInventoryEntry, ...],
        *,
        roots: LegacySourceRootConfiguration,
        root_alias: LegacyRootAlias,
    ) -> Iterator[MaterializedLegacySelection]:
        root = roots.resolve(root_alias)
        try:
            staging_metadata = self.settings.staging_root.lstat()
            if self.settings.staging_root.is_symlink() or not stat.S_ISDIR(
                staging_metadata.st_mode
            ):
                raise OSError("invalid staging root")
            with tempfile.TemporaryDirectory(
                prefix="legacy-selection-materialization-", dir=self.settings.staging_root
            ) as directory:
                staging = Path(directory)
                os.chmod(staging, 0o700)
                staging_fd = os.open(staging, _OPEN_DIRECTORY)
                root_fd = _open_absolute_directory(Path(root.absolute_path))
                try:
                    root_before = os.fstat(root_fd)
                    declarations = tuple(
                        _materialize_entry(
                            root_fd=root_fd,
                            staging_fd=staging_fd,
                            prepared=original,
                        )
                        for original in entries
                    )
                    if _directory_identity(root_before) != _directory_identity(os.fstat(root_fd)):
                        raise LegacySourceSelectionError(
                            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_CHANGED
                        )
                finally:
                    os.close(root_fd)
                    os.close(staging_fd)
                discovered = discover_source_files(staging)
                _require_materialized_set(discovered, declarations, entries)
                yield MaterializedLegacySelection(
                    directory=staging,
                    declarations=declarations,
                )
        except LegacySourceSelectionError:
            raise
        except (OSError, ValueError, IntakeError) as exc:
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID
            ) from exc


def _materialize_entry(
    *,
    root_fd: int,
    staging_fd: int,
    prepared: SelectedInventoryEntry,
) -> IntakeSourceDeclaration:
    entry = prepared.entry
    source_name = PurePosixPath(entry.relative_path).name
    if len(source_name) > 255:
        raise LegacySourceSelectionError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_UNSAFE_PATH
        )
    suffix = PurePosixPath(entry.relative_path).suffix.casefold()
    if not suffix or any(
        character not in ".-0123456789abcdefghijklmnopqrstuvwxyz" for character in suffix
    ):
        raise LegacySourceSelectionError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_MEDIA_INVALID
        )
    staged_name = f"{entry.entry_key}{suffix}"
    destination_fd = -1
    parent_fd = -1
    source_fd = -1
    try:
        parts = PurePosixPath(entry.relative_path).parts
        parent_fd = _open_relative_directory(root_fd, parts[:-1])
        parent_before = os.fstat(parent_fd)
        source_before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(source_before.st_mode)
            or source_before.st_nlink != 1
            or source_before.st_size != entry.size_bytes
        ):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
            )
        source_fd = os.open(parts[-1], _OPEN_READ, dir_fd=parent_fd)
        source_opened = os.fstat(source_fd)
        if _file_identity(source_before) != _file_identity(source_opened):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
            )
        destination_fd = os.open(staged_name, _OPEN_WRITE_EXCLUSIVE, 0o600, dir_fd=staging_fd)
        os.fchmod(destination_fd, 0o600)
        digest = hashlib.sha256()
        copied = 0
        while chunk := os.read(source_fd, READ_CHUNK_BYTES):
            digest.update(chunk)
            copied += len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise OSError("short source materialization write")
                view = view[written:]
        os.fsync(destination_fd)
        source_after = os.fstat(source_fd)
        destination = os.fstat(destination_fd)
        if (
            _file_identity(source_opened) != _file_identity(source_after)
            or _directory_identity(parent_before) != _directory_identity(os.fstat(parent_fd))
            or copied != entry.size_bytes
            or "sha256:" + digest.hexdigest() != entry.content_sha256
            or not stat.S_ISREG(destination.st_mode)
            or destination.st_nlink != 1
            or stat.S_IMODE(destination.st_mode) != 0o600
            or destination.st_size != entry.size_bytes
        ):
            raise LegacySourceSelectionError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
            )
    except LegacySourceSelectionError:
        raise
    except OSError as exc:
        raise LegacySourceSelectionError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
        ) from exc
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        if source_fd >= 0:
            os.close(source_fd)
        if parent_fd >= 0:
            os.close(parent_fd)
    return IntakeSourceDeclaration(
        normalized_relative_path=staged_name,
        original_filename=source_name,
        media_type=entry.media_type or "application/octet-stream",
        declared_role=prepared.selected.declared_intake_role,
        declared_description=(
            f"legacy-selection:{prepared.selected.entry_key};"
            f"corpus:{prepared.selected.intended_corpus_key}"
        ),
    )


def _require_materialized_set(
    discovered: tuple[DiscoveredSource, ...],
    declarations: tuple[IntakeSourceDeclaration, ...],
    entries: tuple[SelectedInventoryEntry, ...],
) -> None:
    actual = {
        source.normalized_relative_path: (source.size_bytes, source.sha256) for source in discovered
    }
    expected = {
        declaration.normalized_relative_path: (
            prepared.entry.size_bytes,
            prepared.entry.content_sha256,
        )
        for declaration, prepared in zip(declarations, entries, strict=True)
    }
    if actual != expected or len(expected) != len(declarations):
        raise LegacySourceSelectionError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID
        )


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute():
        raise OSError("legacy root must be absolute")
    descriptor = os.open("/", _OPEN_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("legacy root is not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            child = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
