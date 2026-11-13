"""One exam's bounded native preparation, canonical publication and existing learning intake.

The HTTP-facing command contains existing source receipts and workbook facts, never
an executable or filesystem path. Only deployment composition supplies the protected
tool Python/converter. CPU preparation can replay after interruption; canonical files
and the accepted asynchronous material run remain owned by their existing services.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningAcceptance,
    MaterialLearningSourceSelection,
)
from eom_catalog_contracts.material_native_intake import (
    CreateNativeMaterialLearningCommand,
    require_native_exam_bundle_sources,
    require_native_exam_bundle_workbook,
)
from eom_catalog_contracts.material_native_prepare import PrepareNativeMaterialExamCommand
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_hwpx_contracts.native_conversion_v2 import (
    NativeHwpConverterSnapshotV2,
    NativeHwpQualifiedConversionReceiptV2,
)
from eom_hwpx_contracts.native_exam_preparation import (
    NATIVE_EXAM_SOURCE_LIMIT,
    NativeExamFilePreparationRequest,
    native_exam_preparation_sha256,
)
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult, SourceRole
from eom_identifiers import sha256_bytes
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.native_exam_preparation import (
    PreparedNativeExamFiles,
)
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_native_publication import (
    MaterialNativeArtifactPublicationService,
    MaterialNativePublication,
    NativePublicationSourcePort,
)
from eom_catalog_service.native_exam_workbook import read_native_exam_workbook
from eom_catalog_service.settings import CatalogSettings


class NativePreparationArtifactPort(Protocol):
    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        schema_ref: str,
        media_type: str,
        sha256: str,
        max_bytes: int,
    ) -> bytes: ...


class NativePreparationToolPort(Protocol):
    def __call__(
        self,
        source_bytes: bytes,
        *,
        request: NativeExamFilePreparationRequest,
        workspace: Path,
        python: Path,
    ) -> PreparedNativeExamFiles: ...


class NativePreparationPublicationPort(Protocol):
    def publish_exam(
        self,
        *,
        operator_id: str,
        source_namespace: str,
        exam_key: str,
        sources: tuple[MaterialLearningSourceSelection, ...],
        question_directory: Path,
        question_results: tuple[NativeItemSplitResult, ...],
        solution_directory: Path,
        solution_results: tuple[NativeItemSplitResult, ...],
        workbook_path: Path,
        parsed_workbook: NativeExamWorkbookDocument,
        conversion_receipts: Mapping[SourceRole, NativeHwpQualifiedConversionReceiptV2]
        | None = None,
    ) -> MaterialNativePublication: ...


class NativePreparationIntakePort(Protocol):
    def create(
        self, command: CreateNativeMaterialLearningCommand
    ) -> MaterialLearningAcceptance: ...


def _file_epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_workbook_input(path: Path, command: PrepareNativeMaterialExamCommand) -> bytes:
    """One private upload hand-off, before parsing; user filename is never a path."""
    try:
        for parent in reversed(path.absolute().parents):
            if not stat.S_ISDIR(parent.lstat().st_mode):
                raise ValueError("MATERIAL_NATIVE_PREPARATION_WORKBOOK_FILE_INVALID")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size != command.workbook_bytes
            ):
                raise ValueError("MATERIAL_NATIVE_PREPARATION_WORKBOOK_FILE_INVALID")
            payload = source.read(command.workbook_bytes + 1)
            if (
                len(payload) != command.workbook_bytes
                or sha256_bytes(payload) != command.workbook_sha256
                or _file_epoch(before) != _file_epoch(os.fstat(source.fileno()))
                or _file_epoch(before) != _file_epoch(path.lstat())
            ):
                raise ValueError("MATERIAL_NATIVE_PREPARATION_WORKBOOK_CHANGED")
            return payload
    except OSError as exc:
        raise ValueError("MATERIAL_NATIVE_PREPARATION_WORKBOOK_FILE_INVALID") from exc


class MaterialNativePreparationService:
    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings,
        *,
        python: Path,
        converter: NativeHwpConverterSnapshotV2,
        tool: NativePreparationToolPort,
        artifacts: NativePreparationArtifactPort | None = None,
        sources: NativePublicationSourcePort | None = None,
        publication: NativePreparationPublicationPort | None = None,
        intake: NativePreparationIntakePort | None = None,
    ) -> None:
        if not python.is_absolute() or not settings.staging_root.is_absolute():
            raise ValueError("MATERIAL_NATIVE_PREPARATION_RUNTIME_CONFIG_INVALID")
        self.python = python
        self.converter = NativeHwpConverterSnapshotV2.model_validate(
            converter.model_dump(mode="json")
        )
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self.artifacts: NativePreparationArtifactPort = (
            artifacts if artifacts is not None else CatalogArtifactService(engine, settings)
        )
        self.sources: NativePublicationSourcePort = (
            sources if sources is not None else MaterialLearningSourceService(engine, settings)
        )
        self.publication: NativePreparationPublicationPort = (
            publication
            if publication is not None
            else MaterialNativeArtifactPublicationService(engine, settings)
        )
        self.intake: NativePreparationIntakePort = (
            intake if intake is not None else MaterialLearningIntakeService(engine, settings)
        )
        self.tool = tool

    def _authorize(self, actor_id: str) -> None:
        with self.sessions() as session:
            authorize_material_learning(session, actor_id)

    def _authorize_sources(self, command: PrepareNativeMaterialExamCommand) -> None:
        self._authorize(command.actor_id)
        for source in command.sources:
            self.sources.resolve(source.source_upload, operator_id=command.actor_id)
        self._authorize(command.actor_id)

    def authorize_upload(self, command: PrepareNativeMaterialExamCommand) -> None:
        """Authenticate the real uploader/source receipts before streaming untrusted metadata."""
        command = PrepareNativeMaterialExamCommand.model_validate(command.model_dump(mode="json"))
        if any(
            source.source_upload.original.bytes > NATIVE_EXAM_SOURCE_LIMIT
            for source in command.sources
        ):
            raise ValueError("MATERIAL_NATIVE_PREPARATION_SOURCE_TOO_LARGE")
        self._authorize_sources(command)

    def _prepare_source(
        self,
        source: MaterialLearningSourceSelection,
        *,
        expected_numbers: tuple[int, ...],
        workspace: Path,
        actor_id: str,
    ) -> PreparedNativeExamFiles:
        self._authorize(actor_id)
        pointer = source.source_upload.original
        if not 1 <= pointer.bytes <= NATIVE_EXAM_SOURCE_LIMIT:
            raise ValueError("MATERIAL_NATIVE_PREPARATION_SOURCE_TOO_LARGE")
        incoming = self.artifacts.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=pointer.bytes,
        )
        if len(incoming) != pointer.bytes or sha256_bytes(incoming) != pointer.sha256:
            raise ValueError("MATERIAL_NATIVE_PREPARATION_SOURCE_CHANGED")
        request = NativeExamFilePreparationRequest.model_validate(
            dict(
                expected_source_sha256=pointer.sha256,
                source_format=source.source_upload.source_format,
                source_role=source.source_role,
                expected_numbers=expected_numbers,
                converter=self.converter.model_dump(mode="json")
                if source.source_upload.source_format == "HWP"
                else None,
            )
        )
        prepared = self.tool(incoming, request=request, workspace=workspace, python=self.python)
        self._authorize(actor_id)
        result = prepared.result
        if (
            prepared.workspace != workspace
            or prepared.workspace.is_symlink()
            or not prepared.workspace.is_dir()
            or result.request_sha256
            != native_exam_preparation_sha256(request.model_dump(mode="json"))
            or result.original_source_sha256 != pointer.sha256
            or result.source_role != request.source_role
            or result.source_format != request.source_format
            or result.expected_numbers != expected_numbers
            or (request.converter is None) != (prepared.conversion_receipt is None)
        ):
            raise ValueError("MATERIAL_NATIVE_PREPARATION_TOOL_RESULT_MISMATCH")
        if prepared.conversion_receipt is not None and (
            prepared.conversion_receipt.snapshot != request.converter
            or prepared.conversion_receipt.evidence.source_sha256 != pointer.sha256
            or prepared.conversion_receipt.normalization.output_sha256
            != result.native_source_sha256
        ):
            raise ValueError("MATERIAL_NATIVE_PREPARATION_CONVERSION_MISMATCH")
        return prepared

    def prepare_and_create(
        self, workbook_path: Path, command: PrepareNativeMaterialExamCommand
    ) -> MaterialLearningAcceptance:
        command = PrepareNativeMaterialExamCommand.model_validate(command.model_dump(mode="json"))
        self.authorize_upload(command)
        raw = _read_workbook_input(workbook_path, command)
        workbook = read_native_exam_workbook(raw, source_sha256=command.workbook_sha256)
        sheets = tuple(sheet for sheet in workbook.worksheets if sheet.rows)
        if len(sheets) != 1:
            raise ValueError("MATERIAL_NATIVE_PREPARATION_WORKSHEET_AMBIGUOUS")
        numbers = tuple(row.question_number for row in sheets[0].rows)
        if not 1 <= len(numbers) <= 128 or numbers != tuple(sorted(set(numbers))):
            raise ValueError("MATERIAL_NATIVE_PREPARATION_QUESTION_NUMBERS_INVALID")
        with tempfile.TemporaryDirectory(
            prefix="material-native-prepare.", dir=self.settings.staging_root
        ) as temporary:
            workspace = Path(temporary)
            staged_workbook = workspace / "metadata.xlsx"
            descriptor = os.open(
                staged_workbook, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as out:
                out.write(raw)
            prepared = {
                selection.source_role: self._prepare_source(
                    selection,
                    expected_numbers=numbers,
                    workspace=workspace / selection.source_role.lower(),
                    actor_id=command.actor_id,
                )
                for selection in command.sources
            }
            conversions: dict[SourceRole, NativeHwpQualifiedConversionReceiptV2] = {
                selection.source_role: receipt
                for selection in command.sources
                if (receipt := prepared[selection.source_role].conversion_receipt) is not None
            }
            self._authorize(command.actor_id)
            publication = self.publication.publish_exam(
                operator_id=command.actor_id,
                source_namespace=command.source_namespace,
                exam_key=command.exam_key,
                sources=command.sources,
                question_directory=prepared["MAIN"].workspace / "items",
                question_results=prepared["MAIN"].split_results,
                solution_directory=prepared["SOLUTIONS"].workspace / "items",
                solution_results=prepared["SOLUTIONS"].split_results,
                workbook_path=staged_workbook,
                parsed_workbook=workbook,
                conversion_receipts=conversions,
            )
            require_native_exam_bundle_sources(
                publication.bundle, command.sources, operator_id=command.actor_id
            )
            require_native_exam_bundle_workbook(publication.bundle, workbook)
            if (
                publication.bundle.source_namespace != command.source_namespace
                or publication.bundle.exam_key != command.exam_key
            ):
                raise ValueError("MATERIAL_NATIVE_PREPARATION_PUBLICATION_MISMATCH")
            self._authorize(command.actor_id)
            accepted = self.intake.create(
                CreateNativeMaterialLearningCommand(
                    actor_id=command.actor_id,
                    idempotency_key=command.idempotency_key,
                    upload=command.upload,
                    sources=command.sources,
                    native_bundle=publication.pointer,
                )
            )
        self._authorize_sources(command)
        return accepted
