"""Continue an already admitted corpus under native Office input and four report slots."""

from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.creative_learning_continuation import (
    CREATIVE_OFFICE_CONTINUATION_REF,
    CREATIVE_PARALLEL_CONTINUATION_REF,
    CreativeLearningExecutionScope,
    CreativeLearningOfficeContinuation,
    CreativeLearningParallelContinuation,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service.repository import effective_permissions
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.creative_office_parallel_controls import (
    release_creative_office_parallel_controls,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.external_item_learning_policy_preparation import (
    ExternalItemLearningControlInputs,
    prepare_office_item_learning_execution_policy,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.control_plane import ExecutionPresetRevision
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_continuation_preparation import _PERMISSIONS
from eom_catalog_service.creative_item_registration import prepare_creative_registration_pack
from eom_catalog_service.creative_learning_cohort import (
    COHORT_ARTIFACT_TYPE,
    read_creative_execution_scope,
)
from eom_catalog_service.creative_learning_proposal import (
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.external_creative_learning_source import (
    CatalogExternalItemLearningSourceAuthorizer,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
)
from eom_catalog_service.settings import CatalogSettings


def prepare_creative_office_continuation(
    engine: Engine,
    *,
    predecessor_revision_id: str,
    controls: ExternalItemLearningControlInputs,
    pack_directory: Path,
    settings: Settings,
    catalog_settings: CatalogSettings,
) -> tuple[CreativeLearningExecutionScope, PublishedControlFileSet]:
    """The admitted owner is reauthorized, not replaced by root or a new browser grant.

    This is the existing supported continuation maintenance pattern. It neither
    starts a worker nor edits a predecessor Workflow/failed record/source/target.
    """
    sessions = build_session_factory(engine)
    artifacts = CatalogArtifactService(engine, catalog_settings)
    publisher = ControlFileSetPublisher(engine, settings)
    previous, publication = read_creative_execution_scope(
        artifacts, publisher, predecessor_revision_id
    )
    parallel = previous.continuation
    if not isinstance(parallel, CreativeLearningParallelContinuation):
        raise ValueError("CREATIVE_OFFICE_CONTINUATION_PARENT_MISMATCH")
    with sessions() as session:
        seed = resolve_completed_creative_learning_proposal(
            session, artifacts, previous.cohort.seed_selection
        )
    operator_id = previous.cohort.requested_by_operator_id
    if seed.operator_id != operator_id or seed.work.source.import_id != previous.cohort.import_id:
        raise ValueError("CREATIVE_CONTINUATION_SEED_MISMATCH")
    authorizer = CatalogExternalItemLearningSourceAuthorizer(
        ExternalItemPreviewProjectionService(engine, settings=catalog_settings)
    )

    def authorize(current: str) -> None:
        if current != operator_id:
            raise ValueError("CREATIVE_CONTINUATION_OWNER_MISMATCH")
        with sessions() as session:
            authorizer.reauthorize(session, operator_id=operator_id, source=seed.work.source)
            if not _PERMISSIONS.issubset(effective_permissions(session, operator_id)):
                raise ValueError("CREATIVE_CONTINUATION_PERMISSION_DENIED")

    authorize(operator_id)
    native = prepare_office_item_learning_execution_policy(
        sessions,
        ControlArtifactPublisher(engine, settings),
        inputs=controls,
        operator_id=operator_id,
        authorize_control_change=authorize,
    )
    policy = release_creative_office_parallel_controls(
        sessions,
        ControlArtifactPublisher(engine, settings),
        extraction_revision_id=native.preset_revision_id,
        analysis_revision_id=previous.analysis_preset.preset_revision_id,
        operator_id=operator_id,
        source_commit=controls.source_commit,
        authorize=authorize,
    )
    pack = prepare_creative_registration_pack(
        engine,
        settings=catalog_settings,
        pack_directory=pack_directory,
        selection=previous.cohort.seed_selection,
    )
    pointer = ArtifactMemberPointer(
        artifact_id=publication.artifact_id,
        artifact_revision_id=publication.artifact_revision_id,
        member_path=publication.primary_file,
        schema_ref=CREATIVE_PARALLEL_CONTINUATION_REF,
        media_type="application/json",
        sha256=publication.primary_sha256,
    )

    def preset_pin(value: ExecutionPresetRevision) -> dict[str, str]:
        return {
            "preset_id": value.preset_id,
            "preset_revision_id": value.preset_revision_id,
            "sha256": value.content_sha256,
        }

    body = {
        "schema_version": "creative-learning-continuation/1.2",
        "parent_cohort": parallel.parent_cohort.model_dump(mode="json"),
        "predecessor_execution": pointer.model_dump(mode="json"),
        "requested_by_operator_id": operator_id,
        "target_set_sha256": previous.cohort.target_set_sha256,
        "source_commit": controls.source_commit,
        "workflow_definition_version": "3.0.0",
        "workflow_definition_sha256": controls.definition.sha256,
        "content_pack_release_id": pack,
        "extraction_preset": preset_pin(policy.extraction),
        "analysis_preset": preset_pin(policy.analysis),
        "extraction_preset_key": "creative-office-learning-four",
        "analysis_preset_key": "creative-knowledge-analysis-office-four",
        "capacity_policy": {
            "capacity_policy_id": policy.capacity.capacity_policy_id,
            "capacity_policy_revision_id": policy.capacity.capacity_policy_revision_id,
            "schema_ref": "eom://schemas/workflow/worker-capacity-policy/1.5",
            "sha256": policy.capacity.content_sha256,
        },
        "max_in_flight_sources": 8,
        "max_report_workers": 4,
        "graph_publication_batch_size": 4,
        "continuation_reason": "NATIVE_OFFICE_FOUR_SLOT_SUCCESSOR",
    }
    identity = content_sha256({k: v for k, v in body.items() if k != "source_commit"})
    key = "creative-office-continuation:" + identity[7:]
    try:
        existing = publisher.find_published(idempotency_key=key, artifact_type=COHORT_ARTIFACT_TYPE)
    except ControlPlaneError as error:
        if error.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        existing = None  # resume the same immutable commit, never create another identity
    if existing is not None:
        scope, existing = read_creative_execution_scope(
            artifacts, publisher, existing.artifact_revision_id
        )
        actual = scope.continuation
        if not isinstance(actual, CreativeLearningOfficeContinuation) or any(
            actual.model_dump(mode="json")[field] != value
            for field, value in body.items()
            if field != "source_commit"
        ):
            raise ValueError("CREATIVE_CONTINUATION_REPLAY_MISMATCH")
        return scope, existing
    body["cohort_id"] = "creativecohort_" + identity[7:39]
    continuation = CreativeLearningOfficeContinuation.model_validate(
        {**body, "cohort_sha256": content_sha256(body)}
    )
    # Compose before committing: wrong owner/parent/target/policy must publish nothing.
    CreativeLearningExecutionScope(previous.cohort, continuation, previous)
    payload = canonical_json_bytes(continuation.model_dump(mode="json"))
    authorize(operator_id)
    with TemporaryDirectory(
        prefix="creative-office-continuation-", dir=settings.staging_root
    ) as raw:
        path = Path(raw) / "office-continuation.json"
        path.write_bytes(payload)
        path.chmod(0o400)
        published = publisher.publish_first_observation(
            members=(
                ControlFileSetMember(
                    path.name,
                    path,
                    sha256_bytes(payload),
                    len(payload),
                    CREATIVE_OFFICE_CONTINUATION_REF,
                    "application/json",
                ),
            ),
            primary_file=path.name,
            artifact_type=COHORT_ARTIFACT_TYPE,
            manifest_version=continuation.schema_version,
            idempotency_key=key,
            source_commit=controls.source_commit,
        )
    authorize(operator_id)
    return read_creative_execution_scope(artifacts, publisher, published.artifact_revision_id)
