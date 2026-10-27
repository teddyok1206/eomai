"""Resolve one creative archive row into an exact, read-only worker source."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_catalog_contracts.external_item_learning_source import (
    EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA,
    ExternalItemLearningSource,
)
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from sqlalchemy.orm import Session

from eom_catalog_service.external_creative_learning_targets import (
    ExternalCreativeLearningTarget,
    get_external_creative_learning_target,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    ResolvedExternalItemPreview,
)


class ExternalCreativeLearningSourceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExternalCreativeLearningInput:
    """Bounded PDF materialization for one authorized worker staging boundary."""

    source: ExternalItemLearningSource
    pdf_bytes: bytes


def _validated_source(
    target: ExternalCreativeLearningTarget,
    resolved: ResolvedExternalItemPreview,
) -> ExternalItemLearningSource:
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


def _open_validated_source(
    session: Session,
    preview_service: ExternalItemPreviewProjectionService,
    *,
    import_id: str,
    external_number: str,
) -> tuple[ExternalItemLearningSource, ResolvedExternalItemPreview]:
    target = get_external_creative_learning_target(
        session, import_id=import_id, external_number=external_number
    )
    resolved = preview_service.open(
        ExternalItemDocumentMediaQuery(
            source_id=target.source_id,
            source_revision_id=target.source_revision_id,
            edition=target.selected_edition,
        )
    )
    try:
        return _validated_source(target, resolved), resolved
    except Exception:
        resolved.member.stream.close()
        raise


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

    source, resolved = _open_validated_source(
        session, preview_service, import_id=import_id, external_number=external_number
    )
    try:
        return source
    finally:
        resolved.member.stream.close()


def read_external_creative_learning_input(
    session: Session,
    preview_service: ExternalItemPreviewProjectionService,
    *,
    import_id: str,
    external_number: str,
) -> ExternalCreativeLearningInput:
    """Resolve current Catalog authority once and materialize its exact PDF once.

    The trusted caller must authorize the operator and pin this source to its
    persisted worker claim. This helper grants neither claim nor source access.
    """

    source, resolved = _open_validated_source(
        session, preview_service, import_id=import_id, external_number=external_number
    )
    expected_bytes = source.preview_manifest.pdf_bytes
    digest = hashlib.sha256()
    payload = bytearray()
    try:
        for chunk in resolved.member.iter_chunks():
            payload.extend(chunk)
            digest.update(chunk)
            if len(payload) > expected_bytes:
                raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PDF_INVALID")
        if (
            len(payload) != expected_bytes
            or "sha256:" + digest.hexdigest() != source.preview_manifest.pdf_sha256
        ):
            raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PDF_INVALID")
        return ExternalCreativeLearningInput(source=source, pdf_bytes=bytes(payload))
    finally:
        resolved.member.stream.close()
