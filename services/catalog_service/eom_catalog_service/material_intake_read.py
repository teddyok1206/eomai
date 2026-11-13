"""Read only explicit committed material versions; parser failure never means use latest."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPreparationInput,
    MaterialPreparedArtifact,
)
from eom_catalog_contracts.material_native_intake import (
    MATERIAL_NATIVE_INTAKE_REF,
    MATERIAL_NATIVE_PREPARATION_REF,
    MATERIAL_NATIVE_PREPARED_REF,
    MaterialIntake,
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparationInput,
    MaterialNativePreparedArtifact,
    MaterialPreparation,
    MaterialPrepared,
)
from eom_identifiers import content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactReader
from eom_catalog_service.material_learning_artifacts import read_material_metadata

_INTAKE_V1 = "eom://schemas/material-learning/intake/1.0"
_PREPARATION_V1 = "eom://schemas/material-learning/preparation-input/1.0"
_PREPARED_V1 = "eom://schemas/material-learning/prepared/1.0"


def _checkpoint_pointer(
    session: Session,
    *,
    artifact_id: str,
    revision_id: str,
    sha256: str,
    member: str,
    permitted_schemas: frozenset[str],
) -> MaterialArtifactMember:
    """Metadata lookup only; bytes and permission are verified by the read owner next."""
    revision = session.get(ArtifactRevisionRecord, revision_id)
    artifact = session.get(ArtifactRecord, artifact_id)
    if (
        revision is None
        or artifact is None
        or not revision.approved
        or not artifact.approved
        or revision.logical_artifact_id != artifact_id
        or revision.content_hash != sha256
        or content_sha256(revision.manifest) != revision.manifest_hash
        or revision.manifest.get("primary_file") != member
    ):
        raise ValueError("MATERIAL_LEARNING_CHECKPOINT_POINTER_INVALID")
    files = revision.manifest.get("files")
    matches = (
        [
            entry
            for entry in files
            if isinstance(entry, Mapping) and entry.get("file_name") == member
        ]
        if isinstance(files, list)
        else []
    )
    if len(matches) != 1:
        raise ValueError("MATERIAL_LEARNING_CHECKPOINT_MEMBER_INVALID")
    actual = matches[0]
    schema = actual.get("schema_ref")
    size = actual.get("bytes")
    if (
        not isinstance(schema, str)
        or schema not in permitted_schemas
        or actual.get("media_type") != "application/json"
        or actual.get("sha256") != sha256
        or type(size) is not int
        or size != revision.content_bytes
        or not 1 <= size <= 4 * 1024 * 1024
    ):
        raise ValueError("MATERIAL_LEARNING_CHECKPOINT_SCHEMA_INVALID")
    return MaterialArtifactMember(
        artifact_id=artifact_id,
        artifact_revision_id=revision_id,
        member_path=member,
        schema_ref=schema,
        media_type="application/json",
        sha256=sha256,
        bytes=size,
    )


def material_intake_pointer(
    session: Session, *, artifact_id: str, revision_id: str, sha256: str
) -> MaterialArtifactMember:
    return _checkpoint_pointer(
        session,
        artifact_id=artifact_id,
        revision_id=revision_id,
        sha256=sha256,
        member="material/intake.json",
        permitted_schemas=frozenset({_INTAKE_V1, MATERIAL_NATIVE_INTAKE_REF}),
    )


def material_preparation_pointer(
    session: Session, *, artifact_id: str, revision_id: str, sha256: str
) -> MaterialArtifactMember:
    return _checkpoint_pointer(
        session,
        artifact_id=artifact_id,
        revision_id=revision_id,
        sha256=sha256,
        member="material/preparation-input.json",
        permitted_schemas=frozenset({_PREPARATION_V1, MATERIAL_NATIVE_PREPARATION_REF}),
    )


def material_prepared_pointer(
    session: Session, *, artifact_id: str, revision_id: str, sha256: str
) -> MaterialArtifactMember:
    return _checkpoint_pointer(
        session,
        artifact_id=artifact_id,
        revision_id=revision_id,
        sha256=sha256,
        member="material/prepared.json",
        permitted_schemas=frozenset({_PREPARED_V1, MATERIAL_NATIVE_PREPARED_REF}),
    )


def read_material_intake(
    artifacts: CatalogArtifactReader,
    pointer: MaterialArtifactMember,
    *,
    authorize: Callable[[], None],
) -> MaterialIntake:
    """Caller binds the pointer to its real actor's material row before this read."""
    authorize()
    if pointer.schema_ref == _INTAKE_V1:
        result: MaterialIntake = read_material_metadata(
            artifacts,
            pointer,
            MaterialLearningIntakeManifest,
            schema_ref=_INTAKE_V1,
            member_path="material/intake.json",
            maximum_bytes=4 * 1024 * 1024,
        )
    elif pointer.schema_ref == MATERIAL_NATIVE_INTAKE_REF:
        result = read_material_metadata(
            artifacts,
            pointer,
            MaterialNativeLearningIntakeManifest,
            schema_ref=MATERIAL_NATIVE_INTAKE_REF,
            member_path="material/intake.json",
            maximum_bytes=4 * 1024 * 1024,
        )
    else:
        raise ValueError("MATERIAL_LEARNING_INTAKE_SCHEMA_UNSUPPORTED")
    authorize()
    return result


def read_material_preparation(
    artifacts: CatalogArtifactReader,
    pointer: MaterialArtifactMember,
    *,
    authorize: Callable[[], None],
) -> MaterialPreparation:
    authorize()
    if pointer.schema_ref == _PREPARATION_V1:
        result: MaterialPreparation = read_material_metadata(
            artifacts,
            pointer,
            MaterialPreparationInput,
            schema_ref=_PREPARATION_V1,
            member_path="material/preparation-input.json",
        )
    elif pointer.schema_ref == MATERIAL_NATIVE_PREPARATION_REF:
        result = read_material_metadata(
            artifacts,
            pointer,
            MaterialNativePreparationInput,
            schema_ref=MATERIAL_NATIVE_PREPARATION_REF,
            member_path="material/preparation-input.json",
        )
    else:
        raise ValueError("MATERIAL_LEARNING_PREPARATION_SCHEMA_UNSUPPORTED")
    authorize()
    return result


def read_material_prepared(
    artifacts: CatalogArtifactReader,
    pointer: MaterialArtifactMember,
    *,
    authorize: Callable[[], None],
) -> MaterialPrepared:
    authorize()
    if pointer.schema_ref == _PREPARED_V1:
        result: MaterialPrepared = read_material_metadata(
            artifacts,
            pointer,
            MaterialPreparedArtifact,
            schema_ref=_PREPARED_V1,
            member_path="material/prepared.json",
        )
    elif pointer.schema_ref == MATERIAL_NATIVE_PREPARED_REF:
        result = read_material_metadata(
            artifacts,
            pointer,
            MaterialNativePreparedArtifact,
            schema_ref=MATERIAL_NATIVE_PREPARED_REF,
            member_path="material/prepared.json",
        )
    else:
        raise ValueError("MATERIAL_LEARNING_PREPARED_SCHEMA_UNSUPPORTED")
    authorize()
    return result
