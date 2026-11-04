"""Durable FIFO delivery of one saved, pinned mixed-source assembly."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from eom_catalog_contracts import (
    CuratedDocumentAssemblyManifestV1,
    CuratedExternalDocumentPlacement,
)
from eom_hwpx_contracts import validate_contract
from eom_hwpx_contracts.curated_build import (
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
    CuratedRegisteredItemInput,
)
from eom_identifiers import (
    content_sha256,
    new_hwpx_build_id,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
)
from eom_operator_identity import ActorContext, ActorSource, ActorType
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from eom_hwpx_manager.application_service import SecureHwpxDownload
from eom_hwpx_manager.application_state import ApplicationBuildState, require_application_transition
from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode


class CuratedAssemblyAuthorization(Protocol):
    def authorize_delivery_build(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDocumentAssemblyManifestV1: ...

    def read_for_delivery(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDocumentAssemblyManifestV1: ...


@dataclass(frozen=True)
class CuratedBuildReceipt:
    build_id: str
    input_plan_sha256: str
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    output_sha256: str
    output_size_bytes: int
    section_count: int
    binary_count: int
    native_table_count: int
    native_equation_count: int


class CuratedBuildPending(RuntimeError):
    """The same live/uncertain external execution must be observed, not replaced."""


class CuratedHwpxRenderer(Protocol):
    def pin_inputs(self, manifest: CuratedDocumentAssemblyManifestV1) -> CuratedHwpxBuildInput: ...

    def finish(
        self,
        record: HwpxCuratedBuildRecord,
        inputs: CuratedHwpxBuildInput,
        *,
        validated: Callable[[str], None],
    ) -> CuratedBuildReceipt:
        """Stage/dispatch once, or recover the same result/commit after interruption."""
        ...

    def build_may_be_active(self, build_id: str) -> bool: ...

    def secure_download(self, record: HwpxCuratedBuildRecord) -> SecureHwpxDownload: ...


class CuratedRecoveryState(StrEnum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True)
class CuratedRecoveryResult:
    state: CuratedRecoveryState
    record: HwpxCuratedBuildRecord | None = None


class CuratedHwpxApplicationService:
    """Own persistence and authorization; only renderer.finish has file side effects."""

    def __init__(
        self,
        engine: Engine,
        *,
        assemblies: CuratedAssemblyAuthorization,
        renderer: CuratedHwpxRenderer,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.assemblies = assemblies
        self.renderer = renderer

    def request_build(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
        idempotency_key: str,
    ) -> tuple[HwpxCuratedBuildRecord, bool]:
        if (
            re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None
            or actor.actor_type is not ActorType.OPERATOR
            or actor.source is not ActorSource.APPLICATION_API
            or actor.operator_id is None
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_REVISION_INELIGIBLE,
                "curated delivery requires an authenticated operator and key",
            )
        manifest = self.assemblies.authorize_delivery_build(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
        )
        request_hash = content_sha256(
            {
                "assembly_id": assembly_id,
                "assembly_revision_id": assembly_revision_id,
                "assembly_manifest_sha256": manifest_sha256,
            }
        )
        # Replay is resolved before choosing today's renderer/presentation release.
        with self.sessions() as session:
            existing = session.scalar(
                select(HwpxCuratedBuildRecord).where(
                    HwpxCuratedBuildRecord.created_by_operator_id == actor.operator_id,
                    HwpxCuratedBuildRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._require_replay(existing, request_hash, manifest)
                session.expunge(existing)
                return existing, False
        inputs = self.renderer.pin_inputs(manifest)
        self._require_inputs(inputs, manifest)
        plan = inputs.model_dump(mode="json")
        validate_contract("curated-build-input", plan)
        initiator = actor.model_copy(update={"permissions": frozenset()}).model_dump(mode="json")
        try:
            with transaction(self.sessions) as session:
                existing = session.scalar(
                    select(HwpxCuratedBuildRecord).where(
                        HwpxCuratedBuildRecord.created_by_operator_id == actor.operator_id,
                        HwpxCuratedBuildRecord.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._require_replay(existing, request_hash, manifest)
                    session.expunge(existing)
                    return existing, False
                record = HwpxCuratedBuildRecord(
                    build_id=new_hwpx_build_id(),
                    assembly_id=assembly_id,
                    assembly_revision_id=assembly_revision_id,
                    assembly_manifest_sha256=manifest_sha256,
                    input_plan=plan,
                    input_plan_sha256=content_sha256(plan),
                    initiator_context=initiator,
                    request_sha256=request_hash,
                    idempotency_key=idempotency_key,
                    created_by_operator_id=actor.operator_id,
                    planned_job_id=new_job_id(),
                    planned_artifact_id=new_logical_artifact_id(),
                    planned_artifact_revision_id=new_revision_id(),
                    state=ApplicationBuildState.REQUESTED.value,
                    validation_state="PENDING",
                    placement_count=len(inputs.placements),
                    resource_version=1,
                    output_filename="eom-assembly.hwpx",
                )
                session.add(record)
                session.flush()
                session.expunge(record)
                return record, True
        except IntegrityError:
            # The unique actor/key constraint is the concurrent admission authority.
            with self.sessions() as session:
                existing = session.scalar(
                    select(HwpxCuratedBuildRecord).where(
                        HwpxCuratedBuildRecord.created_by_operator_id == actor.operator_id,
                        HwpxCuratedBuildRecord.idempotency_key == idempotency_key,
                    )
                )
                if existing is None:
                    raise
                self._require_replay(existing, request_hash, manifest)
                session.expunge(existing)
                return existing, False

    def get_build(self, build_id: str, *, actor: ActorContext) -> HwpxCuratedBuildRecord:
        record = self._record(build_id)
        if actor.operator_id != record.created_by_operator_id:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_BUILD_NOT_FOUND,
                "curated build does not exist for this operator",
            )
        self._authorize(record, actor)
        return record

    def latest_build(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> HwpxCuratedBuildRecord | None:
        manifest = self.assemblies.read_for_delivery(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
        )
        with self.sessions() as session:
            record = session.scalar(
                select(HwpxCuratedBuildRecord)
                .where(
                    HwpxCuratedBuildRecord.assembly_revision_id == assembly_revision_id,
                    HwpxCuratedBuildRecord.created_by_operator_id == actor.operator_id,
                )
                .order_by(
                    HwpxCuratedBuildRecord.created_at.desc(), HwpxCuratedBuildRecord.build_id.desc()
                )
                .limit(1)
            )
            if record is not None:
                self._pinned_inputs(record, manifest)
                session.expunge(record)
            return record

    def process_next(self) -> HwpxCuratedBuildRecord | None:
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(HwpxCuratedBuildRecord)
                .where(
                    HwpxCuratedBuildRecord.state == ApplicationBuildState.REQUESTED.value,
                )
                .order_by(HwpxCuratedBuildRecord.created_at, HwpxCuratedBuildRecord.build_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            self._transition(record, ApplicationBuildState.RUNNING)
            record.started_at = datetime.now(UTC)
            record.resource_version += 1
            session.flush()
            session.expunge(record)
        # The FIFO claim commits before staging or subprocess/Artifact operations.
        with self._build_lock(record.build_id) as locked:
            if not locked:
                return self._record(record.build_id)
            current = self._record(record.build_id)
            if current.state not in {"RUNNING", "VALIDATING"}:
                return current
            return self._finish(current)

    def recover_interrupted(self) -> CuratedRecoveryResult:
        with self.sessions() as session:
            record = session.scalar(
                select(HwpxCuratedBuildRecord)
                .where(
                    HwpxCuratedBuildRecord.state.in_(("RUNNING", "VALIDATING")),
                )
                .order_by(HwpxCuratedBuildRecord.started_at, HwpxCuratedBuildRecord.build_id)
                .limit(1)
            )
            if record is None:
                return CuratedRecoveryResult(CuratedRecoveryState.NONE)
            session.expunge(record)
        with self._build_lock(record.build_id) as locked:
            if not locked or self.renderer.build_may_be_active(record.build_id):
                return CuratedRecoveryResult(CuratedRecoveryState.ACTIVE, record)
            current = self._record(record.build_id)
            if current.state not in {"RUNNING", "VALIDATING"}:
                return CuratedRecoveryResult(CuratedRecoveryState.NONE)
            current = self._finish(current)
            state = (
                CuratedRecoveryState.ACTIVE
                if current.state in {"RUNNING", "VALIDATING"}
                else CuratedRecoveryState.RECOVERED
            )
            return CuratedRecoveryResult(state, current)

    def secure_download(self, build_id: str, *, actor: ActorContext) -> SecureHwpxDownload:
        record = self.get_build(build_id, actor=actor)
        if record.state != "SUCCEEDED" or record.validation_state != "PASS":
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_APPLICATION_DOWNLOAD_UNAVAILABLE,
                "validated curated output is not available",
            )
        return self.renderer.secure_download(record)

    def _record(self, build_id: str) -> HwpxCuratedBuildRecord:
        with self.sessions() as session:
            record = session.get(HwpxCuratedBuildRecord, build_id)
            if record is None:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_APPLICATION_BUILD_NOT_FOUND,
                    "curated build does not exist",
                )
            session.expunge(record)
            return record

    def _authorize(
        self,
        record: HwpxCuratedBuildRecord,
        actor: ActorContext,
    ) -> CuratedHwpxBuildInput:
        manifest = self.assemblies.read_for_delivery(
            record.assembly_id,
            assembly_revision_id=record.assembly_revision_id,
            manifest_sha256=record.assembly_manifest_sha256,
            actor=actor,
        )
        return self._pinned_inputs(record, manifest)

    def _finish(self, record: HwpxCuratedBuildRecord) -> HwpxCuratedBuildRecord:
        try:
            inputs = self._authorize_build(record)
            receipt = self.renderer.finish(
                record,
                inputs,
                validated=lambda job_id: self._validated(record.build_id, job_id),
            )
            with transaction(self.sessions) as session:
                current = session.scalar(
                    select(HwpxCuratedBuildRecord)
                    .where(
                        HwpxCuratedBuildRecord.build_id == record.build_id,
                    )
                    .with_for_update()
                )
                if current is None:
                    raise RuntimeError("curated build disappeared")
                self._complete(current, receipt)
                session.flush()
                session.expunge(current)
                return current
        except CuratedBuildPending:
            return self._record(record.build_id)
        except SQLAlchemyError:
            # Observation/commit ambiguity is recoverable; do not invent a failure
            # or dispatch a second identity after a database connection error.
            raise
        except Exception as exc:
            return self._fail(record.build_id, exc)

    def _validated(self, build_id: str, job_id: str) -> None:
        # Recheck permission/source revocation after rendering, before the
        # renderer crosses its Artifact commit boundary.
        self._authorize_build(self._record(build_id))
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(HwpxCuratedBuildRecord)
                .where(
                    HwpxCuratedBuildRecord.build_id == build_id,
                )
                .with_for_update()
            )
            if record is None or job_id != record.planned_job_id:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "curated validated Job identity differs",
                )
            if record.state == "VALIDATING" and record.platform_job_id == job_id:
                return
            self._transition(record, ApplicationBuildState.VALIDATING)
            record.platform_job_id = job_id
            record.resource_version += 1

    def _authorize_build(self, record: HwpxCuratedBuildRecord) -> CuratedHwpxBuildInput:
        initiator = ActorContext.model_validate(record.initiator_context)
        if initiator.operator_id != record.created_by_operator_id or initiator.permissions:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "curated build initiator metadata differs",
            )
        manifest = self.assemblies.authorize_delivery_build(
            record.assembly_id,
            assembly_revision_id=record.assembly_revision_id,
            manifest_sha256=record.assembly_manifest_sha256,
            actor=initiator,
        )
        return self._pinned_inputs(record, manifest)

    @staticmethod
    def _complete(record: HwpxCuratedBuildRecord, receipt: CuratedBuildReceipt) -> None:
        if (
            receipt.build_id != record.build_id
            or receipt.input_plan_sha256 != record.input_plan_sha256
            or receipt.job_id != record.planned_job_id
            or receipt.job_id != record.platform_job_id
            or receipt.artifact_id != record.planned_artifact_id
            or receipt.artifact_revision_id != record.planned_artifact_revision_id
            or re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.output_sha256) is None
            or not record.placement_count <= receipt.section_count <= 10000
            or not 1 <= receipt.output_size_bytes <= 256 * 1024 * 1024
            or min(receipt.binary_count, receipt.native_table_count, receipt.native_equation_count)
            < 0
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                "curated receipt differs from its pinned build",
            )
        CuratedHwpxApplicationService._transition(record, ApplicationBuildState.SUCCEEDED)
        record.validation_state = "PASS"
        record.section_count = receipt.section_count
        record.binary_count = receipt.binary_count
        record.native_table_count = receipt.native_table_count
        record.native_equation_count = receipt.native_equation_count
        record.output_artifact_id = receipt.artifact_id
        record.output_artifact_revision_id = receipt.artifact_revision_id
        record.output_sha256 = receipt.output_sha256
        record.output_size_bytes = receipt.output_size_bytes
        record.completed_at = datetime.now(UTC)
        record.resource_version += 1

    def _fail(self, build_id: str, error: Exception) -> HwpxCuratedBuildRecord:
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(HwpxCuratedBuildRecord)
                .where(
                    HwpxCuratedBuildRecord.build_id == build_id,
                )
                .with_for_update()
            )
            if record is None:
                raise RuntimeError("curated build disappeared")
            if record.state not in {"SUCCEEDED", "FAILED"}:
                self._transition(record, ApplicationBuildState.FAILED)
                code = getattr(error, "code", None)
                code = code.value if isinstance(code, StrEnum) else code
                record.failure_code = (
                    code
                    if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code)
                    else HwpxManagerErrorCode.HWPX_BUILDER_FAILED.value
                )
                record.validation_state = "FAIL"
                record.completed_at = datetime.now(UTC)
                record.resource_version += 1
            session.flush()
            session.expunge(record)
            return record

    @staticmethod
    def _require_replay(
        record: HwpxCuratedBuildRecord,
        request_hash: str,
        manifest: CuratedDocumentAssemblyManifestV1,
    ) -> None:
        if (
            record.request_sha256 != request_hash
            or record.assembly_id != manifest.assembly_id
            or record.assembly_revision_id != manifest.assembly_revision_id
            or record.assembly_manifest_sha256 != manifest.manifest_sha256
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                "curated HWPX request differs from the original key",
            )
        CuratedHwpxApplicationService._pinned_inputs(record, manifest)

    @staticmethod
    def _pinned_inputs(
        record: HwpxCuratedBuildRecord,
        manifest: CuratedDocumentAssemblyManifestV1,
    ) -> CuratedHwpxBuildInput:
        validate_contract("curated-build-input", record.input_plan)
        inputs = CuratedHwpxBuildInput.model_validate(record.input_plan)
        if record.input_plan_sha256 != content_sha256(record.input_plan):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING, "curated replay input snapshot differs"
            )
        CuratedHwpxApplicationService._require_inputs(inputs, manifest)
        return inputs

    @staticmethod
    def _require_inputs(
        inputs: CuratedHwpxBuildInput,
        manifest: CuratedDocumentAssemblyManifestV1,
    ) -> None:
        if (
            inputs.assembly_id != manifest.assembly_id
            or inputs.assembly_revision_id != manifest.assembly_revision_id
            or inputs.assembly_manifest_sha256 != manifest.manifest_sha256
            or len(inputs.placements) != len(manifest.placements)
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "curated render inputs differ from saved assembly",
            )
        for pinned, source in zip(inputs.placements, manifest.placements, strict=True):
            matches = pinned.position == source.position
            if isinstance(source, CuratedExternalDocumentPlacement):
                matches = (
                    matches
                    and isinstance(pinned, CuratedNativeDocumentInput)
                    and (
                        pinned.document.model_dump() == source.document_artifact.model_dump()
                        and pinned.source_format == source.source_format
                        and pinned.size_bytes == source.document_size_bytes
                    )
                )
            else:
                matches = (
                    matches
                    and isinstance(pinned, CuratedRegisteredItemInput)
                    and (
                        pinned.item_id == source.item_id
                        and pinned.item_revision_id == source.item_revision_id
                        and pinned.item_manifest_sha256 == source.item_manifest_sha256
                    )
                )
            if not matches:
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                    "curated placement pointer or order differs",
                )

    @contextmanager
    def _build_lock(self, build_id: str) -> Iterator[bool]:
        # The separate session lock survives short state transactions, not process
        # death. Explicit unlock avoids returning a locked connection to the pool.
        key = "hwpx-curated:" + build_id
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            acquired = (
                connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key}
                )
                is True
            )
            try:
                yield acquired
            finally:
                if acquired:
                    try:
                        if (
                            connection.scalar(
                                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                                {"key": key},
                            )
                            is not True
                        ):
                            connection.invalidate()
                    except Exception:
                        connection.invalidate()
                        raise

    @staticmethod
    def _transition(record: HwpxCuratedBuildRecord, target: ApplicationBuildState) -> None:
        require_application_transition(ApplicationBuildState(record.state), target)
        record.state = target.value
