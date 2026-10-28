"""Admit one immutable creative source cohort using an actual Studio session."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.creative_learning_cohort import (
    CREATIVE_COHORT_SCHEMA_REF,
    CreativeLearningCohort,
)
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.preset_model_selection import validated_preset
from eom_orchestrator.settings import Settings
from eom_workflow.control_plane import ExecutionPresetRevision, ExecutionPresetRevisionV2
from sqlalchemy import Engine, select, text

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_item_registration import creative_registration_key
from eom_catalog_service.creative_learning_proposal import (
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.creative_registered_report import load_registered_creative_report
from eom_catalog_service.external_creative_learning_source import (
    authorize_external_creative_learning_preparation,
)
from eom_catalog_service.external_creative_learning_targets import (
    list_external_creative_learning_targets,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.settings import CatalogSettings

COHORT_ARTIFACT_TYPE = "control_creative_learning_cohort"


def read_creative_cohort(
    artifacts: CatalogArtifactService,
    publisher: ControlFileSetPublisher,
    revision_id: str,
) -> tuple[CreativeLearningCohort, PublishedControlFileSet]:
    published = publisher.read_published_revision(
        artifact_revision_id=revision_id, artifact_type=COHORT_ARTIFACT_TYPE
    )
    payload = artifacts.read_member(
        artifact_id=published.artifact_id,
        revision_id=published.artifact_revision_id,
        member_path="cohort.json",
        sha256=published.primary_sha256,
        schema_ref=CREATIVE_COHORT_SCHEMA_REF,
        media_type="application/json",
        max_bytes=16 * 1024 * 1024,
    )
    return CreativeLearningCohort.model_validate_json(payload), published


def admit_creative_cohort(
    engine: Engine,
    *,
    actor_provider: Callable[[], ActorContext],
    seed_selection: ExternalItemLearningRoleSelection,
    import_id: str,
    risk_policy_revision_id: str,
    access_policy_revision_id: str,
    source_commit: str,
    settings: Settings,
    catalog_settings: CatalogSettings,
) -> tuple[CreativeLearningCohort, PublishedControlFileSet]:
    sessions = build_session_factory(engine)
    artifacts = CatalogArtifactService(engine, catalog_settings)
    publisher = ControlFileSetPublisher(engine, settings)

    def owner() -> str:
        with sessions() as session:
            operator_id = authorize_external_creative_learning_preparation(
                session, actor_provider()
            )
            required = {
                PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT,
                PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
                PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
                PermissionKey.GENERAL_CHAT_READ,
                PermissionKey.ITEM_READ,
            }
            if not required.issubset(effective_permissions(session, operator_id)):
                raise ValueError("CREATIVE_COHORT_PERMISSION_DENIED")
            return operator_id

    operator_id = owner()
    with sessions() as session, session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        seed = resolve_completed_creative_learning_proposal(session, artifacts, seed_selection)
        if seed.operator_id != operator_id or seed.work.source.import_id != import_id:
            raise ValueError("CREATIVE_COHORT_SEED_MISMATCH")
        registered = session.scalar(
            select(ItemRevisionRecord).where(
                ItemRevisionRecord.registration_key
                == creative_registration_key(seed.work.source.source_id)
            )
        )
        if registered is None:
            raise ValueError("CREATIVE_COHORT_REGISTERED_SEED_MISSING")
        load_registered_creative_report(session, artifacts, registered)
        plan = session.get(ResolvedExecutionPlanRecord, seed_selection.plan_id)
        if plan is None:
            raise ValueError("CREATIVE_COHORT_PLAN_MISSING")
        extraction_row = session.get(ExecutionPresetRevisionRecord, plan.preset_revision_id)
        logical = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "creative-knowledge-analysis"
            )
        )
        analysis_row = (
            session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
            if logical
            else None
        )
        if extraction_row is None or analysis_row is None:
            raise ValueError("CREATIVE_COHORT_POLICY_MISSING")
        extraction, analysis = validated_preset(extraction_row), validated_preset(analysis_row)
        if (
            extraction.state != "RELEASED"
            or analysis.state != "RELEASED"
            or extraction.capacity_policy_revision_id != plan.capacity_policy_revision_id
            or analysis.capacity_policy_revision_id != plan.capacity_policy_revision_id
        ):
            raise ValueError("CREATIVE_COHORT_POLICY_MISMATCH")
        risk = KnowledgeAnalysisApplicationService.risk_policy(session, risk_policy_revision_id)
        policy = KnowledgeRetrievalApplicationService(
            engine, catalog_settings
        ).read_released_access_policy(access_policy_revision_id)
        targets: list[dict[str, str | int]] = []
        after = None
        while True:
            page = list_external_creative_learning_targets(
                session, import_id=import_id, after_number=after, limit=25
            )
            targets.extend(
                {
                    "source_id": entry.source_id,
                    "source_revision_id": entry.source_revision_id,
                    "external_number": entry.external_number,
                    "observation_sha256": entry.observation_sha256,
                    "selected_edition": entry.selected_edition,
                }
                for entry in page.entries
            )
            after = page.next_after_number
            if after is None:
                break

        def pins(preset: ExecutionPresetRevision | ExecutionPresetRevisionV2) -> dict[str, str]:
            return {
                "preset_id": preset.preset_id,
                "preset_revision_id": preset.preset_revision_id,
                "sha256": preset.content_sha256,
            }

        body = {
            "schema_version": "creative-learning-cohort/1.0",
            "import_id": import_id,
            "requested_by_operator_id": operator_id,
            "source_commit": source_commit,
            "targets": targets,
            "target_set_sha256": content_sha256(targets),
            "seed_external_number": seed.work.source.external_number,
            "seed_selection": seed_selection.model_dump(mode="json"),
            "extraction_preset": pins(extraction),
            "analysis_preset": pins(analysis),
            "capacity_policy_revision_id": plan.capacity_policy_revision_id,
            "workflow_definition_sha256": plan.canonical_document["workflow_definition_sha256"],
            "content_pack_release_id": registered.content_pack_release_id,
            "risk_policy_revision_id": risk_policy_revision_id,
            "risk_policy_sha256": risk.content_sha256,
            "access_policy_revision_id": access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "registration_policy": "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
        }
    identity = content_sha256({key: value for key, value in body.items() if key != "source_commit"})
    key = "creative-cohort:" + identity[7:]
    if owner() != operator_id:
        raise ValueError("CREATIVE_COHORT_OWNER_CHANGED")
    previous = publisher.find_published(idempotency_key=key, artifact_type=COHORT_ARTIFACT_TYPE)
    if previous is not None:
        return read_creative_cohort(artifacts, publisher, previous.artifact_revision_id)
    body.update(
        cohort_id="creativecohort_" + identity[7:39],
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    cohort = CreativeLearningCohort.model_validate({**body, "cohort_sha256": content_sha256(body)})
    payload = canonical_json_bytes(cohort.model_dump(mode="json"))
    with TemporaryDirectory(prefix="creative-cohort-", dir=settings.staging_root) as raw:
        path = Path(raw) / "cohort.json"
        path.write_bytes(payload)
        path.chmod(0o400)
        published = publisher.publish(
            members=(
                ControlFileSetMember(
                    "cohort.json",
                    path,
                    sha256_bytes(payload),
                    len(payload),
                    CREATIVE_COHORT_SCHEMA_REF,
                    "application/json",
                ),
            ),
            primary_file="cohort.json",
            artifact_type=COHORT_ARTIFACT_TYPE,
            manifest_version=cohort.schema_version,
            idempotency_key=key,
            source_commit=source_commit,
            created_at=cohort.created_at,
        )
    return cohort, published
