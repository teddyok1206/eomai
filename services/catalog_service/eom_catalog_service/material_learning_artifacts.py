"""Small material metadata at the existing Orchestrator publication/read boundary."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_orchestrator.state_machine import JobState
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class MaterialPrimaryMetadata:
    pointer: MaterialArtifactMember
    created_at: datetime


def find_material_publication(
    publisher: ControlFileSetPublisher, *, idempotency_key: str, artifact_type: str
) -> ArtifactMemberPointer | None:
    """Absent or resumable original only; never hide FAILED or damaged success."""
    try:
        return publisher.find_published_primary_member(
            idempotency_key=idempotency_key, artifact_type=artifact_type
        )
    except ControlPlaneError as error:
        if error.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        state = publisher.publication_state(
            idempotency_key=idempotency_key, artifact_type=artifact_type
        )
        if state in {None, JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            raise
        return None


def pin_material_primary(
    session: Session, pointer: ArtifactMemberPointer
) -> MaterialPrimaryMetadata:
    """One indexed metadata lookup; byte/permission resolution stays with its owners."""
    row = (
        session.execute(
            select(ArtifactRevisionRecord, ArtifactRecord)
            .join(
                ArtifactRecord,
                ArtifactRecord.logical_artifact_id == ArtifactRevisionRecord.logical_artifact_id,
            )
            .where(ArtifactRevisionRecord.revision_id == pointer.artifact_revision_id)
        )
        .tuples()
        .one_or_none()
    )
    if row is None:
        raise MaterialLearningSourceError("MATERIAL_LEARNING_METADATA_POINTER_INVALID")
    revision, artifact = row
    if (
        artifact.logical_artifact_id != pointer.artifact_id
        or not revision.approved
        or not artifact.approved
        or revision.content_hash != pointer.sha256
        or revision.manifest.get("primary_file") != pointer.member_path
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_METADATA_POINTER_INVALID")
    return MaterialPrimaryMetadata(
        MaterialArtifactMember(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            bytes=revision.content_bytes,
        ),
        revision.created_at,
    )


def publish_material_metadata(
    artifacts: CatalogArtifactService,
    settings: CatalogSettings,
    model: BaseModel,
    *,
    member_path: str,
    schema_ref: str,
    idempotency_key: str,
    artifact_type: str,
) -> MaterialArtifactMember:
    encoded = canonical_json_bytes(model.model_dump(mode="json"))
    digest = sha256_bytes(encoded)
    with tempfile.TemporaryDirectory(
        prefix="material-metadata.", dir=settings.staging_root
    ) as temporary:
        path = Path(temporary) / "metadata.json"
        with path.open("xb") as stream:
            stream.write(encoded)
        artifact = artifacts.commit_file_set(
            files={member_path: path},
            primary_file=member_path,
            artifact_type=artifact_type,
            idempotency_key=idempotency_key,
            request={"schema_ref": schema_ref, "sha256": digest},
            result={"sha256": digest},
            file_metadata={
                member_path: {"schema_ref": schema_ref, "media_type": "application/json"}
            },
            expected_file_sha256={member_path: digest},
        )
    return MaterialArtifactMember(
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.revision_id,
        member_path=member_path,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=digest,
        bytes=len(encoded),
    )


def read_material_metadata[Model: BaseModel](
    artifacts: CatalogArtifactService,
    pointer: MaterialArtifactMember,
    model: type[Model],
    *,
    schema_ref: str,
    member_path: str,
    maximum_bytes: int = 2 * 1024 * 1024,
) -> Model:
    if (
        pointer.schema_ref != schema_ref
        or pointer.member_path != member_path
        or pointer.media_type != "application/json"
        or pointer.bytes > maximum_bytes
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_METADATA_POINTER_INVALID")
    value = artifacts.read_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=pointer.sha256,
        max_bytes=pointer.bytes,
    )
    if len(value) != pointer.bytes:
        raise MaterialLearningSourceError("MATERIAL_LEARNING_METADATA_SIZE_MISMATCH")
    return model.model_validate_json(value)
