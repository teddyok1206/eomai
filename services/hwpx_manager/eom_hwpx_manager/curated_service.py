"""Recover one fixed-unit render and publish through the existing Artifact owner."""

from __future__ import annotations

import os
from collections.abc import Callable

from eom_catalog_contracts.curated_document_slots import CuratedDeliveryManifest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.curated_delivery_inputs import CuratedDeliveryInputs
from eom_hwpx_contracts.curated_mixed import CuratedMixedRenderResult
from eom_hwpx_contracts.curated_occurrences import (
    CuratedBuildInput,
    CuratedHwpxBuildInputV2,
    parse_mixed_render_result,
)
from eom_hwpx_contracts.validation import parse_json_object
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.repository import ensure_protocol_version, submit_structured_job
from eom_orchestrator.state_machine import JobState, record_job_observation, transition_job
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from eom_hwpx_manager.adapter import hash_stable_regular_file, read_stable_regular_file
from eom_hwpx_manager.application_adapter import FixedCuratedBuilderAdapter
from eom_hwpx_manager.application_service import SecureHwpxDownload
from eom_hwpx_manager.curated_application_service import CuratedBuildPending, CuratedBuildReceipt
from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord
from eom_hwpx_manager.curated_materialization import CuratedInputMaterializer
from eom_hwpx_manager.curated_output_acceptance import verify_curated_output
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.protocol import curated_protocol_identity

ARTIFACT_TYPE = "hwpx-curated-build"
OUTPUT_MEMBER = "assembled.hwpx"
OUTPUT_SCHEMA = "eom://schemas/hwpx/curated-editable-document/1.0"
OUTPUT_MEDIA = "application/hwp+zip"
DISPATCH_EVENT = "HWPX_CURATED_DISPATCHED"


def _invalid(message: str) -> HwpxManagerError:
    return HwpxManagerError(HwpxManagerErrorCode.HWPX_RESULT_INVALID, message)


class CuratedHwpxService:
    """No queue ownership or worker calls; only bounded local render and publication.

    The application service holds the build's advisory lock. Job identity is
    reserved before dispatch; a completed local result or Artifact publication
    is recovered under those same IDs, never a new build or rewritten failure.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        pins: CuratedDeliveryInputs,
        adapter: FixedCuratedBuilderAdapter,
        materializer: CuratedInputMaterializer,
        artifacts: CatalogArtifactService,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.pins = pins
        self.adapter = adapter
        self.materializer = materializer
        self.artifacts = artifacts

    def pin_inputs(
        self, manifest: CuratedDeliveryManifest, *, actor: ActorContext
    ) -> CuratedBuildInput:
        return self.pins.pin_inputs(manifest, actor=actor)

    def build_may_be_active(self, build_id: str) -> bool:
        return self.adapter.build_may_be_active(build_id)

    @staticmethod
    def _key(record: HwpxCuratedBuildRecord) -> str:
        return "hwpx-curated:" + record.build_id

    def _reserve(self, record: HwpxCuratedBuildRecord) -> JobState:
        protocol, schema_hash = curated_protocol_identity(record.input_plan["schema_version"])
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, protocol, schema_hash)
            job, _created = submit_structured_job(
                session,
                job_id=record.planned_job_id,
                protocol_version=protocol,
                idempotency_key=self._key(record),
                task_type=ARTIFACT_TYPE,
                request=record.input_plan,
                logical_artifact_id=record.planned_artifact_id,
                revision_id=record.planned_artifact_revision_id,
            )
            if (
                job.job_id != record.planned_job_id
                or job.logical_artifact_id != record.planned_artifact_id
                or job.revision_id != record.planned_artifact_revision_id
                or content_sha256(job.request) != record.input_plan_sha256
                or job.protocol_version != protocol
                or job.task_type != ARTIFACT_TYPE
            ):
                raise _invalid("curated publication Job differs from its reserved identity")
            return JobState(job.status)

    def _claim_dispatch(self, record: HwpxCuratedBuildRecord) -> bool:
        with transaction(self.sessions) as session:
            # The build advisory lock serializes dispatch. The Job row lock also
            # keeps its observation sequence consistent with publication events.
            job = session.scalar(
                select(JobRecord).where(JobRecord.job_id == record.planned_job_id).with_for_update()
            )
            if job is None or job.status != JobState.CREATED.value:
                raise _invalid("curated dispatch Job is not in CREATED")
            previous = session.scalar(
                select(JobEventRecord.event_id)
                .where(JobEventRecord.job_id == job.job_id, JobEventRecord.event == DISPATCH_EVENT)
                .limit(1)
            )
            if previous is not None:
                return False
            record_job_observation(
                session,
                job.job_id,
                DISPATCH_EVENT,
                expected_state=JobState.CREATED,
                data={"build_id": record.build_id, "input_plan_sha256": record.input_plan_sha256},
            )
            return True

    def finish(
        self,
        record: HwpxCuratedBuildRecord,
        inputs: CuratedBuildInput,
        *,
        validated: Callable[[str], None],
    ) -> CuratedBuildReceipt:
        if (
            inputs.model_dump(mode="json") != record.input_plan
            or content_sha256(record.input_plan) != record.input_plan_sha256
        ):
            raise _invalid("curated publication input snapshot differs")
        state = self._reserve(record)
        if state is JobState.SUCCEEDED:
            validated(record.planned_job_id)
            return self._completed(record)
        if state not in {JobState.CREATED, JobState.COMMITTING}:
            raise _invalid("curated publication has immutable terminal failure evidence")
        if self.build_may_be_active(record.build_id):
            raise CuratedBuildPending("curated fixed-unit execution is still active or uncertain")
        workspace = self.adapter.open_workspace(record.build_id)
        staged = self.materializer.stage(workspace, build_id=record.build_id, inputs=inputs)
        self.adapter.write_json(workspace, "input-plan.json", record.input_plan)
        self.adapter.write_json(workspace, "request.json", staged.request.model_dump(mode="json"))
        result_path = workspace / "result.json"
        try:
            if not result_path.exists() and not result_path.is_symlink():
                if state is JobState.COMMITTING or not self._claim_dispatch(record):
                    # The fixed execution ended without a result. Preserve its
                    # interruption, not an unbounded automatic re-render loop.
                    raise _invalid("curated execution ended without a recoverable result")
                try:
                    run = self.adapter.run(
                        workspace,
                        self.adapter.operation,
                        ["--request", "request.json", "--result", "result.json"],
                        workspace / "manager-logs",
                    )
                except HwpxManagerError:
                    if self.build_may_be_active(record.build_id):
                        raise CuratedBuildPending(
                            "curated fixed-unit execution has not finished"
                        ) from None
                    if not result_path.is_file():
                        raise
                else:
                    if run.exit_code != 0 and not result_path.is_file():
                        raise _invalid("curated fixed-unit execution produced no result")
            maximum = 16 * 1024**2 if isinstance(inputs, CuratedHwpxBuildInputV2) else 1024**2
            raw = parse_json_object(read_stable_regular_file(result_path, max_bytes=maximum))
            result = parse_mixed_render_result(raw)
            if result.profile != inputs.profile:
                raise _invalid("curated result profile differs from its input")
            if result.status != "SUCCEEDED":
                self._record_failure(record, result)
                raise _invalid(
                    "curated Builder rejected the pinned source at its recorded position"
                )
            accepted = verify_curated_output(workspace, staged, result)
            validated(record.planned_job_id)
        except CuratedBuildPending:
            raise
        except SQLAlchemyError:
            raise
        except Exception:
            self._fail_created_job(record)
            raise
        files = {
            OUTPUT_MEMBER: workspace / "output/assembled.hwpx",
            "input-plan.json": workspace / "input-plan.json",
            "render-request.json": workspace / "request.json",
            "render-result.json": result_path,
        }
        expected = {
            name: hash_stable_regular_file(
                path, max_bytes=256 * 1024**2 if name == OUTPUT_MEMBER else maximum
            )
            for name, path in files.items()
        }
        if expected[OUTPUT_MEMBER] != accepted.sha256:
            raise _invalid("curated output changed before Artifact staging")
        try:
            protocol, schema_hash = curated_protocol_identity(inputs.schema_version)
            artifact = self.artifacts.commit_file_set(
                files=files,
                primary_file=OUTPUT_MEMBER,
                artifact_type=ARTIFACT_TYPE,
                idempotency_key=self._key(record),
                request=record.input_plan,
                result=result.model_dump(mode="json"),
                protocol_version=protocol,
                protocol_schema_hash=schema_hash,
                expected_file_sha256=expected,
                file_metadata={
                    OUTPUT_MEMBER: {"schema_ref": OUTPUT_SCHEMA, "media_type": OUTPUT_MEDIA},
                    "input-plan.json": {
                        "schema_ref": f"eom://schemas/hwpx/{inputs.schema_version}",
                        "media_type": "application/json",
                    },
                    "render-request.json": {
                        "schema_ref": f"eom://schemas/hwpx/{staged.request.schema_version}",
                        "media_type": "application/json",
                    },
                    "render-result.json": {
                        "schema_ref": f"eom://schemas/hwpx/{result.schema_version}",
                        "media_type": "application/json",
                    },
                },
            )
        except (OSError, SQLAlchemyError) as exc:
            raise CuratedBuildPending(
                "curated Artifact publication must resume under the same IDs"
            ) from exc
        if (artifact.job_id, artifact.artifact_id, artifact.revision_id) != (
            record.planned_job_id,
            record.planned_artifact_id,
            record.planned_artifact_revision_id,
        ):
            raise _invalid("curated committed Artifact identity differs")
        return self._completed(record)

    def _record_failure(
        self, record: HwpxCuratedBuildRecord, result: CuratedMixedRenderResult
    ) -> None:
        with transaction(self.sessions) as session:
            record_job_observation(
                session,
                record.planned_job_id,
                "HWPX_CURATED_RENDER_REJECTED",
                expected_state=JobState.CREATED,
                data={
                    "build_id": record.build_id,
                    "failure_code": result.failure_code,
                    "failure_position": result.failure_position,
                },
            )

    def _fail_created_job(self, record: HwpxCuratedBuildRecord) -> None:
        with transaction(self.sessions) as session:
            job = session.scalar(
                select(JobRecord).where(JobRecord.job_id == record.planned_job_id).with_for_update()
            )
            if job is not None and job.status == JobState.CREATED.value:
                transition_job(
                    session,
                    job.job_id,
                    JobState.FAILED,
                    "HWPX_CURATED_VALIDATION_FAILED",
                    data={"build_id": record.build_id},
                )

    def _completed(self, record: HwpxCuratedBuildRecord) -> CuratedBuildReceipt:
        with self.sessions() as session:
            row = session.execute(
                select(JobRecord, ArtifactRecord, ArtifactRevisionRecord)
                .join(ArtifactRecord, ArtifactRecord.job_id == JobRecord.job_id)
                .join(ArtifactRevisionRecord, ArtifactRevisionRecord.job_id == JobRecord.job_id)
                .where(
                    JobRecord.job_id == record.planned_job_id,
                )
            ).one_or_none()
            if row is None:
                raise _invalid("curated committed publication is missing")
            job, artifact, revision = row
            if (
                job.status != JobState.SUCCEEDED.value
                or not artifact.approved
                or not revision.approved
                or artifact.logical_artifact_id != record.planned_artifact_id
                or artifact.artifact_type != ARTIFACT_TYPE
                or revision.logical_artifact_id != artifact.logical_artifact_id
                or revision.revision_id != record.planned_artifact_revision_id
                or revision.manifest_hash != content_sha256(revision.manifest)
                or revision.manifest.get("job_id") != record.planned_job_id
                or revision.manifest.get("logical_artifact_id") != record.planned_artifact_id
                or revision.manifest.get("revision_id") != record.planned_artifact_revision_id
                or revision.manifest.get("primary_file") != OUTPUT_MEMBER
                or job.request != record.input_plan
            ):
                raise _invalid("curated committed publication pointer differs")
            result = parse_mixed_render_result(revision.result)
            expected_profile = record.input_plan["profile"]
            if result.profile != expected_profile:
                raise _invalid("committed curated result profile differs")
            members = [
                member
                for member in revision.manifest.get("files", [])
                if member.get("file_name") == OUTPUT_MEMBER
            ]
            if len(members) != 1 or (
                members[0].get("sha256") != result.output_sha256
                or members[0].get("bytes") != result.output_size_bytes
                or members[0].get("schema_ref") != OUTPUT_SCHEMA
                or members[0].get("media_type") != OUTPUT_MEDIA
                or result.build_id != record.build_id
                or result.assembly_revision_id != record.assembly_revision_id
                or result.assembly_manifest_sha256 != record.assembly_manifest_sha256
                or result.input_plan_sha256 != record.input_plan_sha256
                or result.status != "SUCCEEDED"
                or revision.content_hash != result.output_sha256
                or revision.content_bytes != result.output_size_bytes
            ):
                raise _invalid("curated committed output member or result differs")
            assert result.output_sha256 is not None and result.output_size_bytes is not None
            return CuratedBuildReceipt(
                record.build_id,
                record.input_plan_sha256,
                job.job_id,
                artifact.logical_artifact_id,
                revision.revision_id,
                result.output_sha256,
                result.output_size_bytes,
                len(result.section_source_positions),
                result.binary_count,
                result.native_table_count,
                result.native_equation_count,
            )

    def secure_download(self, record: HwpxCuratedBuildRecord) -> SecureHwpxDownload:
        receipt = self._completed(record)
        opened = self.artifacts.open_verified_member(
            artifact_id=receipt.artifact_id,
            revision_id=receipt.artifact_revision_id,
            member_path=OUTPUT_MEMBER,
            sha256=receipt.output_sha256,
            schema_ref=OUTPUT_SCHEMA,
            media_type=OUTPUT_MEDIA,
            max_bytes=256 * 1024**2,
        )
        try:
            if opened.content_length != receipt.output_size_bytes:
                raise _invalid("curated download length differs")
            return SecureHwpxDownload(
                os.dup(opened.stream.fileno()),
                record.output_filename,
                opened.content_length,
                opened.sha256,
            )
        finally:
            opened.stream.close()
