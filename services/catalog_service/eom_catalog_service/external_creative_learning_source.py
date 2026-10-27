"""Resolve one creative archive row into an exact, read-only worker source."""

from __future__ import annotations

from eom_catalog_contracts.external_item_learning_source import (
    EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA,
    ExternalItemLearningSource,
)
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from sqlalchemy.orm import Session

from eom_catalog_service.external_creative_learning_targets import (
    get_external_creative_learning_target,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
)


class ExternalCreativeLearningSourceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_external_creative_learning_source(
    session: Session,
    preview_service: ExternalItemPreviewProjectionService,
    *,
    import_id: str,
    external_number: str,
) -> ExternalItemLearningSource:
    """Reauthorize original and derivative before staging, without opening NAS paths.

    The indexed U lookup is O(log n). PDF member validation streams bounded bytes
    once inside the existing Catalog Artifact boundary. A later worker claim must
    resolve this same immutable source again; this DTO grants no execution right.
    """

    target = get_external_creative_learning_target(
        session, import_id=import_id, external_number=external_number
    )
    query = ExternalItemDocumentMediaQuery(
        source_id=target.source_id,
        source_revision_id=target.source_revision_id,
        edition=target.selected_edition,
    )
    resolved = preview_service.open(query)
    try:
        manifest = resolved.manifest
        if (
            manifest.source_id != target.source_id
            or manifest.source_revision_id != target.source_revision_id
            or manifest.edition != target.selected_edition
            or manifest.source_file_id != target.source_file_id
            or manifest.source_artifact_id != target.artifact_id
            or manifest.source_artifact_revision_id != target.artifact_revision_id
            or manifest.source_sha256 != target.document_sha256
            or manifest.source_media_type != target.document_media_type
            or manifest.source_bytes != target.document_size_bytes
            or resolved.member.sha256 != manifest.pdf_sha256
            or resolved.member.content_length != manifest.pdf_bytes
        ):
            raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_POINTER_MISMATCH")
        value: dict[str, object] = {
            "schema_version": "external-item-learning-source/1.0",
            "import_id": target.import_id,
            "source_namespace": target.source_namespace,
            "source_id": target.source_id,
            "source_revision_id": target.source_revision_id,
            "external_number": target.external_number,
            "origin_kind": target.origin_kind,
            "observation_sha256": target.observation_sha256,
            "selected_edition": target.selected_edition,
            "preview_artifact_id": resolved.artifact_id,
            "preview_artifact_revision_id": resolved.artifact_revision_id,
            "preview_manifest": manifest.model_dump(mode="json"),
        }
        value["input_sha256"] = content_sha256(value)
        validate_contract(EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA, value)
        return ExternalItemLearningSource.model_validate(value)
    finally:
        resolved.member.stream.close()
