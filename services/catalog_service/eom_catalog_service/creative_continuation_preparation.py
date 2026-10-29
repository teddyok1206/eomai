"""Prepare a source-visual successor of one already admitted creative source set."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.creative_learning_cohort import CREATIVE_COHORT_SCHEMA_REF
from eom_catalog_contracts.creative_learning_continuation import (
    CREATIVE_CONTINUATION_REF,
    CreativeLearningContinuation,
    CreativeLearningExecutionScope,
    validate_creative_continuation_parent,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.creative_source_controls import release_creative_source_controls
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.compiler import compile_definition
from eom_workflow_runner.external_item_learning_admission import (
    validate_external_item_learning_definition,
)
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.creative_item_registration import (
    CreativeItemRegistrationService,
    prepare_creative_registration_pack,
)
from eom_catalog_service.creative_learning_cohort import (
    COHORT_ARTIFACT_TYPE,
    read_creative_cohort,
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

_PERMISSIONS = frozenset(
    {
        PermissionKey.EXECUTION_PRESET_MANAGE,
        PermissionKey.CONTENT_PACK_RELEASE,
        PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT,
        PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.GENERAL_CHAT_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
    }
)


def prepare_creative_source_continuation(
    engine: Engine,
    *,
    parent_revision_id: str,
    instruction_directory: Path,
    pack_directory: Path,
    definition_path: Path,
    source_commit: str,
    settings: Settings,
    catalog_settings: CatalogSettings,
) -> tuple[CreativeLearningExecutionScope, PublishedControlFileSet]:
    """No new browser identity: current source/control rights derive from the admitted owner.

    This installed maintenance application may only retain the exact parent's
    targets/operator/analysis/risk/access/capacity pins. It prepares controls and a
    small immutable successor; it does not START a worker, mutate history or edit
    the parent Artifact. The existing root owner performs later claims separately.
    """
    sessions = build_session_factory(engine)
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("CREATIVE_CONTINUATION_SOURCE_COMMIT_INVALID")
    artifacts = CatalogArtifactService(engine, catalog_settings)
    publisher = ControlFileSetPublisher(engine, settings)
    parent, parent_publication = read_creative_cohort(artifacts, publisher, parent_revision_id)
    operator_id = parent.requested_by_operator_id
    with sessions() as session:
        seed = resolve_completed_creative_learning_proposal(
            session, artifacts, parent.seed_selection
        )
        if seed.operator_id != operator_id or seed.work.source.import_id != parent.import_id:
            raise ValueError("CREATIVE_CONTINUATION_SEED_MISMATCH")
    source_authorizer = CatalogExternalItemLearningSourceAuthorizer(
        ExternalItemPreviewProjectionService(engine, settings=catalog_settings)
    )

    def authorize(current: str) -> None:
        if current != operator_id:
            raise ValueError("CREATIVE_CONTINUATION_OWNER_MISMATCH")
        with sessions() as session:
            source_authorizer.reauthorize(session, operator_id=operator_id, source=seed.work.source)
            if not _PERMISSIONS.issubset(effective_permissions(session, operator_id)):
                raise ValueError("CREATIVE_CONTINUATION_PERMISSION_DENIED")

    authorize(operator_id)
    compiled = compile_definition(definition_path, {"support"})
    pack = compile_pack(pack_directory)
    if (
        (compiled.definition.definition_key, compiled.definition.definition_version)
        != ("external-item-learning", "2.0.0")
        or pack.manifest.pack.key != "external-creative-item"
        or not any(
            entry.key == "external-item-learning" and "2.0.0" in entry.versions
            for entry in pack.manifest.compatibility.workflow_definitions
        )
    ):
        raise ValueError("CREATIVE_CONTINUATION_DEFINITION_INVALID")
    seed_target = next(
        target for target in parent.targets if target.external_number == parent.seed_external_number
    )
    registered = CreativeItemRegistrationService(
        engine,
        content_pack_release_id=parent.content_pack_release_id,
        publisher=publisher,
        source_commit=parent.source_commit,
        settings=catalog_settings,
    ).find_registered_source(seed_target, requested_by_operator_id=operator_id)
    if registered is None or registered.lineage.selection != parent.seed_selection:
        raise ValueError("CREATIVE_CONTINUATION_REGISTERED_SEED_MISSING")
    extraction = release_creative_source_controls(
        sessions,
        ControlArtifactPublisher(engine, settings),
        baseline_revision_id=parent.extraction_preset.preset_revision_id,
        capacity_revision_id=parent.capacity_policy_revision_id,
        platform_payload=(instruction_directory / "platform.md").read_bytes(),
        role_payload=(instruction_directory / "external-item-learning.md").read_bytes(),
        operator_id=operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )
    with sessions.begin() as session:
        authorize(operator_id)
        definition, _ = import_workflow_definition(session, compiled)
        validate_external_item_learning_definition(definition)
    pack_id = prepare_creative_registration_pack(
        engine,
        settings=catalog_settings,
        pack_directory=pack_directory,
        selection=parent.seed_selection,
    )
    parent_pointer = ArtifactMemberPointer(
        artifact_id=parent_publication.artifact_id,
        artifact_revision_id=parent_publication.artifact_revision_id,
        member_path="cohort.json",
        schema_ref=CREATIVE_COHORT_SCHEMA_REF,
        media_type="application/json",
        sha256=parent_publication.primary_sha256,
    )
    body = {
        "schema_version": "creative-learning-continuation/1.0",
        "parent_cohort": parent_pointer.model_dump(mode="json"),
        "requested_by_operator_id": operator_id,
        "target_set_sha256": parent.target_set_sha256,
        "source_commit": source_commit,
        "workflow_definition_version": "2.0.0",
        "workflow_definition_sha256": compiled.sha256,
        "extraction_preset": {
            "preset_id": extraction.preset_id,
            "preset_revision_id": extraction.preset_revision_id,
            "sha256": extraction.content_sha256,
        },
        "content_pack_release_id": pack_id,
        "continuation_reason": "SOURCE_VISUAL_CONTRACT_SUCCESSOR",
    }
    # Preserve the first recorded source commit on exact replay. Maintenance code
    # changes do not by themselves authorize another target set or worker run.
    identity = content_sha256({key: value for key, value in body.items() if key != "source_commit"})
    key = "creative-continuation:" + identity[7:]
    authorize(operator_id)
    try:
        existing = publisher.find_published(idempotency_key=key, artifact_type=COHORT_ARTIFACT_TYPE)
    except ControlPlaneError as exc:
        if exc.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        existing = None  # same immutable source/pins can resume the existing commit
    if existing is not None:
        scope, published = read_creative_execution_scope(
            artifacts, publisher, existing.artifact_revision_id
        )
        actual = scope.continuation
        if actual is None or any(
            actual.model_dump(mode="json")[field] != value
            for field, value in body.items()
            if field != "source_commit"
        ):
            raise ValueError("CREATIVE_CONTINUATION_REPLAY_MISMATCH")
        return scope, published
    body["cohort_id"] = "creativecohort_" + identity[7:39]
    continuation = CreativeLearningContinuation.model_validate(
        {**body, "cohort_sha256": content_sha256(body)}
    )
    validate_creative_continuation_parent(continuation, parent, parent_pointer)
    payload = canonical_json_bytes(continuation.model_dump(mode="json"))
    with TemporaryDirectory(prefix="creative-continuation-", dir=settings.staging_root) as raw:
        path = Path(raw) / "continuation.json"
        path.write_bytes(payload)
        path.chmod(0o400)
        authorize(operator_id)
        published = publisher.publish_first_observation(
            members=(
                ControlFileSetMember(
                    "continuation.json",
                    path,
                    sha256_bytes(payload),
                    len(payload),
                    CREATIVE_CONTINUATION_REF,
                    "application/json",
                ),
            ),
            primary_file="continuation.json",
            artifact_type=COHORT_ARTIFACT_TYPE,
            manifest_version=continuation.schema_version,
            idempotency_key=key,
            source_commit=source_commit,
        )
    authorize(operator_id)
    return read_creative_execution_scope(artifacts, publisher, published.artifact_revision_id)
