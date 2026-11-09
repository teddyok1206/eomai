"""Shared read of the committed curated Artifact, with no rendering or file I/O.

Callers own source authorization. The unique Job delivery key resolves only this
build's immutable publication; a missing/unfinished publication never selects latest.
"""

from dataclasses import dataclass

from eom_hwpx_contracts.curated_occurrences import (
    parse_curated_build_input,
    parse_mixed_render_result,
)
from eom_identifiers import content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.state_machine import JobState
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

CURATED_ARTIFACT_TYPE = "hwpx-curated-build"
CURATED_OUTPUT_MEMBER = "assembled.hwpx"
CURATED_OUTPUT_SCHEMA = "eom://schemas/hwpx/curated-editable-document/1.0"
CURATED_OUTPUT_MEDIA = "application/hwp+zip"


@dataclass(frozen=True, slots=True)
class CuratedCommittedOutput:
    build_id: str
    assembly_id: str
    assembly_revision_id: str
    assembly_manifest_sha256: str
    input_plan_sha256: str
    profile: str
    job_id: str
    artifact_id: str
    artifact_revision_id: str
    artifact_sha256: str
    output_sha256: str
    output_size_bytes: int
    section_count: int
    binary_count: int
    native_table_count: int
    native_equation_count: int


def read_curated_committed_output(session: Session, build_id: str) -> CuratedCommittedOutput:
    """Indexed publication lookup, then the same metadata checks used by recovery."""
    row = session.execute(
        select(JobRecord, ArtifactRecord, ArtifactRevisionRecord)
        .join(ArtifactRecord, ArtifactRecord.job_id == JobRecord.job_id)
        .join(ArtifactRevisionRecord, ArtifactRevisionRecord.job_id == JobRecord.job_id)
        .where(JobRecord.idempotency_key == "hwpx-curated:" + build_id)
    ).one_or_none()
    if row is None:
        raise ValueError("curated committed publication is missing")
    job, artifact, revision = row
    if (
        job.status != JobState.SUCCEEDED.value
        or job.task_type != CURATED_ARTIFACT_TYPE
        or job.request_hash
        != content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
        or not artifact.approved
        or not revision.approved
        or artifact.logical_artifact_id != job.logical_artifact_id
        or artifact.artifact_type != CURATED_ARTIFACT_TYPE
        or revision.logical_artifact_id != artifact.logical_artifact_id
        or revision.revision_id != job.revision_id
        or revision.manifest_hash != content_sha256(revision.manifest)
        or revision.manifest.get("job_id") != job.job_id
        or revision.manifest.get("logical_artifact_id") != job.logical_artifact_id
        or revision.manifest.get("revision_id") != job.revision_id
        or revision.manifest.get("primary_file") != CURATED_OUTPUT_MEMBER
    ):
        raise ValueError("curated committed publication pointer differs")
    try:
        inputs = parse_curated_build_input(job.request)
        result = parse_mixed_render_result(revision.result)
    except SchemaError as exc:
        raise ValueError("curated committed publication schema differs") from exc
    input_hash = content_sha256(job.request)
    members = [
        member
        for member in revision.manifest.get("files", [])
        if isinstance(member, dict) and member.get("file_name") == CURATED_OUTPUT_MEMBER
    ]
    if len(members) != 1 or (
        members[0].get("sha256") != result.output_sha256
        or members[0].get("bytes") != result.output_size_bytes
        or members[0].get("schema_ref") != CURATED_OUTPUT_SCHEMA
        or members[0].get("media_type") != CURATED_OUTPUT_MEDIA
        or result.build_id != build_id
        or result.assembly_revision_id != inputs.assembly_revision_id
        or result.assembly_manifest_sha256 != inputs.assembly_manifest_sha256
        or result.input_plan_sha256 != input_hash
        or result.profile != inputs.profile
        or result.status != "SUCCEEDED"
        or revision.content_hash != result.output_sha256
        or revision.content_bytes != result.output_size_bytes
    ):
        raise ValueError("curated committed output member or result differs")
    assert result.output_sha256 is not None and result.output_size_bytes is not None
    return CuratedCommittedOutput(
        build_id=build_id,
        assembly_id=inputs.assembly_id,
        assembly_revision_id=inputs.assembly_revision_id,
        assembly_manifest_sha256=inputs.assembly_manifest_sha256,
        input_plan_sha256=input_hash,
        profile=inputs.profile,
        job_id=job.job_id,
        artifact_id=artifact.logical_artifact_id,
        artifact_revision_id=revision.revision_id,
        artifact_sha256=revision.content_hash,
        output_sha256=result.output_sha256,
        output_size_bytes=result.output_size_bytes,
        section_count=len(result.section_source_positions),
        binary_count=result.binary_count,
        native_table_count=result.native_table_count,
        native_equation_count=result.native_equation_count,
    )
