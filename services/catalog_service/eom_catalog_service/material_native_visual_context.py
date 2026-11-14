"""Resolve a task's exact optional Native visual checkpoint through Catalog readers."""

from collections.abc import Callable

from eom_catalog_contracts.material_native_visual_preparation import (
    MATERIAL_NATIVE_VISUAL_PREPARED_REF,
    MaterialNativeVisualPreparedArtifact,
)
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactReader
from eom_catalog_service.material_intake_read import (
    material_prepared_pointer,
    read_material_prepared,
)
from eom_catalog_service.material_learning_models import MaterialLearningRunRecord


def read_native_visual_prepared_for_run(
    session: Session,
    artifacts: CatalogArtifactReader,
    run: MaterialLearningRunRecord,
    *,
    authorize: Callable[[], None],
) -> MaterialNativeVisualPreparedArtifact | None:
    """No inferred latest or hidden alternate pointer; historical V1/V2 remain historical."""
    authorize()
    identity = (run.prepared_artifact_id, run.prepared_artifact_revision_id, run.prepared_sha256)
    if identity == (None, None, None):
        return None
    artifact_id, revision_id, digest = identity
    if artifact_id is None or revision_id is None or digest is None:
        raise ValueError("MATERIAL_LEARNING_CHECKPOINT_MISSING")
    pointer = material_prepared_pointer(
        session, artifact_id=artifact_id, revision_id=revision_id, sha256=digest
    )
    if pointer.schema_ref != MATERIAL_NATIVE_VISUAL_PREPARED_REF:
        return None
    prepared = read_material_prepared(artifacts, pointer, authorize=authorize)
    if not isinstance(prepared, MaterialNativeVisualPreparedArtifact):
        raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARED_SCHEMA_MISMATCH")
    if prepared.material_revision_id != run.material_revision_id:
        raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARED_SOURCE_MISMATCH")
    authorize()
    return prepared
