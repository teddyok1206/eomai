"""Resolve one creative archive row into an exact, read-only worker source."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.external_item_learning_source import (
    EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA,
    ExternalItemLearningSource,
)
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
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


_ADMISSION_PERMISSIONS = frozenset(
    {
        PermissionKey.CONTENT_INTAKE_READ,
        PermissionKey.WORKFLOW_START,
        PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
    }
)


def authorize_external_creative_learning_claim(
    session: Session, operator_id: str
) -> frozenset[PermissionKey]:
    """Check the persisted task owner without borrowing a browser session."""

    # Submission and its late check may share an identity map. Re-read current
    # revocation/password state instead of accepting the earlier ORM snapshot.
    operator = session.get(OperatorRecord, operator_id, populate_existing=True)
    if (
        operator is None
        or operator.status != "ACTIVE"
        or operator.deleted_at is not None
        or operator.must_change_password
    ):
        raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED")
    permissions = effective_permissions(session, operator_id)
    if not _ADMISSION_PERMISSIONS.issubset(permissions):
        raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED")
    return permissions


def _authorize_submission(session: Session, actor: ActorContext) -> frozenset[PermissionKey]:
    """Recheck a live interactive session before admitting a new task."""

    if (
        actor.actor_type is not ActorType.OPERATOR
        or actor.source is not ActorSource.APPLICATION_API
        or actor.operator_id is None
        or actor.session_id is None
    ):
        raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED")
    api_session = session.get(ApiSessionRecord, actor.session_id, populate_existing=True)
    now = datetime.now(UTC)
    if (
        api_session is None
        or api_session.operator_id != actor.operator_id
        or api_session.revoked_at is not None
        or api_session.authenticated_at != actor.authentication_time
        or api_session.absolute_expires_at <= now
        or api_session.idle_expires_at <= now
    ):
        raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED")
    return authorize_external_creative_learning_claim(session, actor.operator_id)


def authorize_external_creative_learning_preparation(session: Session, actor: ActorContext) -> str:
    """Use the actual current session and four permissions, without opening source bytes."""

    permissions = _authorize_submission(session, actor)
    if PermissionKey.EXECUTION_PRESET_MANAGE not in permissions or actor.operator_id is None:
        raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED")
    return actor.operator_id


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
    expected_source_revision_id: str,
    expected_observation_sha256: str,
    expected_edition: int,
) -> tuple[ExternalItemLearningSource, ResolvedExternalItemPreview]:
    target = get_external_creative_learning_target(
        session, import_id=import_id, external_number=external_number
    )
    if (
        target.source_revision_id != expected_source_revision_id
        or target.observation_sha256 != expected_observation_sha256
        or target.selected_edition != expected_edition
    ):
        raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_STALE")
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
    actor: ActorContext,
    import_id: str,
    external_number: str,
    expected_source_revision_id: str,
    expected_observation_sha256: str,
    expected_edition: int,
) -> ExternalItemLearningSource:
    """Reauthorize original and derivative before staging, without opening NAS paths.

    The indexed U lookup is O(log n). PDF member validation streams bounded bytes
    once inside the existing Catalog Artifact boundary. A later worker claim must
    resolve this same immutable source again; this DTO grants no execution right.
    """

    _authorize_submission(session, actor)
    source, resolved = _open_validated_source(
        session,
        preview_service,
        import_id=import_id,
        external_number=external_number,
        expected_source_revision_id=expected_source_revision_id,
        expected_observation_sha256=expected_observation_sha256,
        expected_edition=expected_edition,
    )
    try:
        return source
    finally:
        resolved.member.stream.close()


def reauthorize_external_creative_learning_claim_source(
    session: Session,
    preview_service: ExternalItemPreviewProjectionService,
    *,
    operator_id: str,
    import_id: str,
    external_number: str,
    expected_source_revision_id: str,
    expected_observation_sha256: str,
    expected_edition: int,
) -> ExternalItemLearningSource:
    """Reauthorize a persisted claim's owner and its exact current source.

    The caller must derive ``operator_id`` from its durable task, not worker
    input. This is a Catalog read boundary; it does not create or claim a job.
    """

    authorize_external_creative_learning_claim(session, operator_id)
    source, resolved = _open_validated_source(
        session,
        preview_service,
        import_id=import_id,
        external_number=external_number,
        expected_source_revision_id=expected_source_revision_id,
        expected_observation_sha256=expected_observation_sha256,
        expected_edition=expected_edition,
    )
    try:
        return source
    finally:
        resolved.member.stream.close()


class CatalogExternalItemLearningSourceAuthorizer:
    """Catalog adapter for the Workflow application's source-authorization port."""

    def __init__(self, preview: ExternalItemPreviewProjectionService) -> None:
        self.preview = preview

    def reauthorize(
        self, session: Session, *, operator_id: str, source: ExternalItemLearningSource
    ) -> ExternalItemLearningSource:
        return reauthorize_external_creative_learning_claim_source(
            session,
            self.preview,
            operator_id=operator_id,
            import_id=source.import_id,
            external_number=source.external_number,
            expected_source_revision_id=source.source_revision_id,
            expected_observation_sha256=source.observation_sha256,
            expected_edition=source.selected_edition,
        )


def read_external_creative_learning_input(
    session: Session,
    preview_service: ExternalItemPreviewProjectionService,
    *,
    actor: ActorContext,
    import_id: str,
    external_number: str,
    expected_source_revision_id: str,
    expected_observation_sha256: str,
    expected_edition: int,
) -> ExternalCreativeLearningInput:
    """Resolve current Catalog authority once and materialize its exact PDF once.

    This rechecks the operator's live session and current permissions before
    opening the source. The caller must still bind this input to its persisted
    worker claim. This helper grants neither claim nor worker source access.
    """

    _authorize_submission(session, actor)
    source, resolved = _open_validated_source(
        session,
        preview_service,
        import_id=import_id,
        external_number=external_number,
        expected_source_revision_id=expected_source_revision_id,
        expected_observation_sha256=expected_observation_sha256,
        expected_edition=expected_edition,
    )
    return _materialize_exact_pdf(source, resolved)


def read_external_creative_learning_claim_input(
    session: Session,
    preview_service: ExternalItemPreviewProjectionService,
    *,
    operator_id: str,
    import_id: str,
    external_number: str,
    expected_source_revision_id: str,
    expected_observation_sha256: str,
    expected_edition: int,
) -> ExternalCreativeLearningInput:
    """Open the exact PDF for a persisted task owner at the claim boundary.

    The caller must bind ``operator_id`` to its durable claim. A worker-provided
    operator ID or stale browser session is never an authorization substitute.
    """

    authorize_external_creative_learning_claim(session, operator_id)
    source, resolved = _open_validated_source(
        session,
        preview_service,
        import_id=import_id,
        external_number=external_number,
        expected_source_revision_id=expected_source_revision_id,
        expected_observation_sha256=expected_observation_sha256,
        expected_edition=expected_edition,
    )
    return _materialize_exact_pdf(source, resolved)


def _materialize_exact_pdf(
    source: ExternalItemLearningSource, resolved: ResolvedExternalItemPreview
) -> ExternalCreativeLearningInput:
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
