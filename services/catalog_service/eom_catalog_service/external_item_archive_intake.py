"""Catalog application bridge from a fixed ZIP envelope to normal Content Intake.

This is a one-time operator use case. The existing Intake/Orchestrator owner commits
validated source artifacts; this bridge only creates temporary local workspaces.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select

from eom_catalog_service.external_item_archive import ExternalItemArchiveInventory
from eom_catalog_service.external_item_archive_staging import (
    plan_external_item_archive_batches,
    stage_external_item_archive_batch,
)
from eom_catalog_service.external_item_import_preparation import CommittedExternalItemSource
from eom_catalog_service.intake_service import IntakeService, IntakeSourceDeclaration
from eom_catalog_service.models import ContentIntakeSourceFileRecord

_WORKBOOK_MAX_BYTES = 100 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


class ExternalItemIntakeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommittedExternalItemWorkbook:
    source_file_id: str
    artifact_id: str
    artifact_revision_id: str
    sha256: str


class ExternalItemArchiveIntakeService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        self.intake = IntakeService(engine)

    def commit_workbook(
        self, workbook_path: Path, *, expected_sha256: str, received_by: str
    ) -> CommittedExternalItemWorkbook:
        """Copy a bounded, exact workbook to an isolated Intake workspace."""

        with TemporaryDirectory(prefix="eom-external-workbook-") as temporary:
            target = Path(temporary) / "workbook.xlsx"
            _copy_exact_regular_file(workbook_path, target, expected_sha256)
            batch = self.intake.create(
                Path(temporary),
                batch_name="external-item-notion-integrated-science-workbook",
                received_by=received_by,
                purpose="Source-only external Item workbook; no Item Registry admission",
                source_declarations=(
                    IntakeSourceDeclaration(
                        normalized_relative_path="workbook.xlsx",
                        original_filename=workbook_path.name,
                        media_type=(
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        ),
                        declared_role="DATA",
                        declared_description="Immutable original external Item metadata workbook",
                    ),
                ),
            )
        with self.sessions() as session:
            source = session.scalar(
                select(ContentIntakeSourceFileRecord).where(
                    ContentIntakeSourceFileRecord.intake_batch_id == batch.intake_batch_id,
                    ContentIntakeSourceFileRecord.relative_path == "source/workbook.xlsx",
                )
            )
            if source is None or source.sha256 != expected_sha256:
                raise ExternalItemIntakeError(
                    "EXTERNAL_ITEM_WORKBOOK_INTAKE_INVALID", "committed workbook differs"
                )
            return CommittedExternalItemWorkbook(
                source_file_id=source.source_file_id,
                artifact_id=source.artifact_id,
                artifact_revision_id=source.artifact_revision_id,
                sha256=source.sha256,
            )

    def commit_archive_documents(
        self,
        archive_path: Path,
        inventory: ExternalItemArchiveInventory,
        *,
        received_by: str,
    ) -> tuple[CommittedExternalItemSource, ...]:
        """Commit all HWP/HWPX observations in bounded, replayable Intake batches."""

        committed: list[CommittedExternalItemSource] = []
        batches = plan_external_item_archive_batches(inventory)
        for number, members in enumerate(batches, start=1):
            with TemporaryDirectory(prefix="eom-external-archive-") as temporary:
                staged = stage_external_item_archive_batch(
                    archive_path, inventory, members, Path(temporary) / "source"
                )
                declarations = (
                    *(
                        IntakeSourceDeclaration(
                            normalized_relative_path=document.relative_path,
                            original_filename=document.original_filename,
                            media_type=document.media_type,
                            declared_role="DATA",
                            declared_description=(
                                f"External Item archive {inventory.archive_sha256}; "
                                f"member {document.member_name}"
                            )[:500],
                        )
                        for document in staged.documents
                    ),
                    IntakeSourceDeclaration(
                        normalized_relative_path=staged.index_relative_path,
                        original_filename=staged.index_relative_path,
                        media_type="application/json",
                        declared_role="DATA",
                        declared_description="Pinned archive member-to-Intake source index",
                    ),
                )
                batch = self.intake.create(
                    staged.source_directory,
                    batch_name=f"external-item-notion-integrated-science-archive-{number:02d}",
                    received_by=received_by,
                    purpose=f"Source-only external Item archive {inventory.archive_sha256}",
                    source_declarations=declarations,
                )
            with self.sessions() as session:
                source_files = {
                    source.relative_path: source
                    for source in session.scalars(
                        select(ContentIntakeSourceFileRecord).where(
                            ContentIntakeSourceFileRecord.intake_batch_id == batch.intake_batch_id
                        )
                    )
                }
                if len(source_files) != len(staged.documents) + 1:
                    raise ExternalItemIntakeError(
                        "EXTERNAL_ITEM_ARCHIVE_INTAKE_INVALID", "committed batch differs"
                    )
                for document in staged.documents:
                    source = source_files.get("source/" + document.relative_path)
                    if (
                        source is None
                        or source.sha256 != document.sha256
                        or source.original_filename != document.original_filename
                        or source.media_type != document.media_type
                    ):
                        raise ExternalItemIntakeError(
                            "EXTERNAL_ITEM_ARCHIVE_INTAKE_INVALID", "committed document differs"
                        )
                    committed.append(
                        CommittedExternalItemSource(
                            source_file_id=source.source_file_id,
                            sha256=source.sha256,
                            original_filename=source.original_filename,
                        )
                    )
        return tuple(committed)


def _copy_exact_regular_file(source_path: Path, target: Path, expected_sha256: str) -> None:
    try:
        descriptor = os.open(
            source_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= _WORKBOOK_MAX_BYTES
            ):
                raise ExternalItemIntakeError(
                    "EXTERNAL_ITEM_WORKBOOK_UNSAFE", "workbook file is unsafe"
                )
            digest = hashlib.sha256()
            output_descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(output_descriptor, "wb") as output:
                while chunk := source.read(_CHUNK_BYTES):
                    digest.update(chunk)
                    output.write(chunk)
            after = os.fstat(source.fileno())
            if "sha256:" + digest.hexdigest() != expected_sha256 or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise ExternalItemIntakeError(
                    "EXTERNAL_ITEM_WORKBOOK_CHANGED", "workbook bytes changed"
                )
    except OSError as exc:
        raise ExternalItemIntakeError(
            "EXTERNAL_ITEM_WORKBOOK_UNAVAILABLE", "workbook file cannot be staged"
        ) from exc
