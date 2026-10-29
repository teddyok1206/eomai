"""Prepare/resume one source from an already admitted immutable cohort.

Only the trusted local owner launches PDF tooling; it uses the existing eom-image
sandbox. Codex execution is exclusively the existing Orchestrator queue/lease.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.creative_learning_cohort import (
    CreativeCohortTarget,
    CreativeLearningCohort,
)
from eom_catalog_contracts.creative_learning_continuation import CreativeLearningExecutionScope
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.external_item_learning_page_publication import (
    external_item_learning_page_artifact,
    publish_external_item_learning_pages,
)
from eom_orchestrator.external_item_learning_page_render import render_external_item_learning_pages
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.preset_model_selection import validated_preset
from eom_orchestrator.settings import Settings
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.models import ExternalItemLearningWorkerRequest
from eom_workflow_runner.external_item_learning_preparation import (
    prepare_external_item_learning_workflow,
)
from eom_workflow_runner.external_item_learning_recovery import (
    prepare_unstarted_external_item_learning_recovery,
    resolve_external_item_learning_recovery,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import (
    admitted_workflow_definition,
    load_persisted_workflow_request,
)
from sqlalchemy import Engine, select

from eom_catalog_service.creative_preview_preparation import prepare_creative_preview
from eom_catalog_service.external_creative_learning_source import (
    CatalogExternalItemLearningSourceAuthorizer,
    read_external_creative_learning_claim_input,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    ExternalItemPreviewUnavailable,
)
from eom_catalog_service.settings import CatalogSettings


def creative_cohort_workflow_key(
    cohort: CreativeLearningCohort,
    target: CreativeCohortTarget,
    *,
    execution_cohort_id: str | None = None,
) -> str:
    return (
        "creative-cohort-work:"
        + content_sha256(
            {
                "cohort_id": execution_cohort_id or cohort.cohort_id,
                "source_revision_id": target.source_revision_id,
                "requested_by_operator_id": cohort.requested_by_operator_id,
            }
        )[7:]
    )


class CreativeCohortPreparationService:
    def __init__(
        self,
        engine: Engine,
        *,
        cohort: CreativeLearningCohort,
        settings: Settings,
        catalog_settings: CatalogSettings,
        scope: CreativeLearningExecutionScope | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.cohort, self.settings = cohort, settings
        self.scope = scope or CreativeLearningExecutionScope(cohort)
        if self.scope.cohort != cohort:
            raise ValueError("CREATIVE_COHORT_SCOPE_MISMATCH")
        self.targets = {entry.source_id: entry for entry in cohort.targets}
        self.pages = ControlFileSetPublisher(engine, settings)
        self.preview = ExternalItemPreviewProjectionService(engine, settings=catalog_settings)
        self.source = CatalogExternalItemLearningSourceAuthorizer(self.preview)

    def prepare(self, target: CreativeCohortTarget) -> ExternalItemLearningRoleSelection:
        if self.targets.get(target.source_id) != target:
            raise ValueError("CREATIVE_COHORT_TARGET_NOT_ADMITTED")
        key = creative_cohort_workflow_key(
            self.cohort, target, execution_cohort_id=self.scope.cohort_id
        )
        with self.sessions() as session:
            if (
                target.external_number == self.cohort.seed_external_number
                and self.scope.continuation is None
            ):
                workflow = session.get(
                    WorkflowInstanceRecord, self.cohort.seed_selection.workflow_id
                )
            else:
                workflow = session.scalar(
                    select(WorkflowInstanceRecord).where(
                        WorkflowInstanceRecord.idempotency_key == key
                    )
                )
            if workflow is not None:
                workflow = resolve_external_item_learning_recovery(session, workflow)
                original = load_persisted_workflow_request(
                    workflow.initial_request
                ).worker_request()
                if not isinstance(original, ExternalItemLearningWorkerRequest):
                    raise ValueError("CREATIVE_COHORT_WORKFLOW_TYPE_MISMATCH")
                source = original.work_input.source
                if (
                    workflow.created_actor_type != "human"
                    or workflow.created_actor_id != self.cohort.requested_by_operator_id
                    or workflow.definition_hash != self.scope.workflow_definition_sha256
                    or workflow.definition_version != self.scope.workflow_definition_version
                    or source.source_id != target.source_id
                    or source.source_revision_id != target.source_revision_id
                    or source.observation_sha256 != target.observation_sha256
                    or source.selected_edition != target.selected_edition
                    or source.import_id != self.cohort.import_id
                ):
                    raise ValueError("CREATIVE_COHORT_WORKFLOW_SOURCE_MISMATCH")
                self.source.reauthorize(
                    session, operator_id=self.cohort.requested_by_operator_id, source=source
                )
                plan = validate_external_item_learning_execution_plan(
                    session.scalar(
                        select(ResolvedExecutionPlanRecord).where(
                            ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
                        )
                    ),
                    workflow_id=workflow.workflow_id,
                    step_key="extract",
                    request=original,
                )
                if (
                    plan.preset_id != self.scope.extraction_preset.preset_id
                    or plan.preset_revision_id != self.scope.extraction_preset.preset_revision_id
                    or plan.preset_sha256 != self.scope.extraction_preset.sha256
                    or plan.capacity_policy_revision_id != self.cohort.capacity_policy_revision_id
                ):
                    raise ValueError("CREATIVE_COHORT_WORKFLOW_POLICY_MISMATCH")
                step = session.scalar(
                    select(WorkflowStepRunRecord).where(
                        WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                        WorkflowStepRunRecord.step_key == "extract",
                        WorkflowStepRunRecord.attempt == 1,
                    )
                )
                if step is None:
                    raise ValueError("CREATIVE_COHORT_WORKFLOW_STEP_MISSING")
                recovered = ExternalItemLearningRoleSelection(
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                    plan_id=plan.plan_id,
                    plan_sha256=plan.plan_sha256,
                    work_input_sha256=original.work_input.request_sha256,
                )
                if (
                    target.external_number == self.cohort.seed_external_number
                    and self.scope.continuation is None
                    and recovered != self.cohort.seed_selection
                ):
                    raise ValueError("CREATIVE_COHORT_SEED_SELECTION_MISMATCH")
                return recovered
        with self.sessions() as session:
            self._ensure_preview(target)
            resolved = read_external_creative_learning_claim_input(
                session,
                self.preview,
                operator_id=self.cohort.requested_by_operator_id,
                import_id=self.cohort.import_id,
                external_number=target.external_number,
                expected_source_revision_id=target.source_revision_id,
                expected_observation_sha256=target.observation_sha256,
                expected_edition=target.selected_edition,
            )
            if resolved.source.source_id != target.source_id:
                raise ValueError("CREATIVE_COHORT_SOURCE_MISMATCH")
        with TemporaryDirectory(
            prefix="creative-cohort-page-", dir=self.settings.staging_root
        ) as raw:
            rendered = render_external_item_learning_pages(
                resolved.source, resolved.pdf_bytes, workspace=Path(raw) / "rendered"
            )
            artifact = publish_external_item_learning_pages(
                self.pages, rendered, source_commit=self.scope.source_commit
            )
            body = {
                "schema_version": "external-item-learning-work-input/1.0",
                "request_id": "extlearnreq_" + uuid5(NAMESPACE_URL, key).hex,
                "source": resolved.source.model_dump(mode="json"),
                "page_set": rendered.manifest.model_dump(mode="json"),
                "page_artifact": external_item_learning_page_artifact(artifact).model_dump(
                    mode="json"
                ),
            }
            work = ExternalItemLearningWorkInput.model_validate(
                {**body, "request_sha256": content_sha256(body)}
            )
            with self.sessions.begin() as session:
                definition = admitted_workflow_definition(
                    session,
                    definition_key="external-item-learning",
                    definition_version=self.scope.workflow_definition_version,
                )
                preset_row = session.get(
                    ExecutionPresetRevisionRecord, self.scope.extraction_preset.preset_revision_id
                )
                preset = validated_preset(preset_row) if preset_row else None
                if (
                    definition is None
                    or definition.definition_hash != self.scope.workflow_definition_sha256
                    or not isinstance(preset, ExecutionPresetRevision)
                    or preset.content_sha256 != self.scope.extraction_preset.sha256
                ):
                    raise ValueError("CREATIVE_COHORT_PREPARATION_POLICY_MISMATCH")
                prepared = prepare_external_item_learning_workflow(
                    session,
                    definition=definition,
                    work=work,
                    operator_id=self.cohort.requested_by_operator_id,
                    idempotency_key=key,
                    source_authorizer=self.source,
                    page_publisher=self.pages,
                    expected_preset=preset,
                )
            return prepared.selection

    def recover_unstarted(self, workflow_id: str) -> ExternalItemLearningRoleSelection:
        """Explicitly prepare one admitted source after a proven no-Job failure.

        Original cohort/source/controls and historical FAILED remain unchanged.
        The Workflow application owns the successor transaction and audit link.
        """
        with self.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            if workflow is None:
                raise ValueError("CREATIVE_COHORT_RECOVERY_WORKFLOW_MISSING")
            if workflow.created_actor_id != self.cohort.requested_by_operator_id:
                raise ValueError("CREATIVE_COHORT_RECOVERY_OWNER_MISMATCH")
            request = load_persisted_workflow_request(workflow.initial_request).worker_request()
            if not isinstance(request, ExternalItemLearningWorkerRequest):
                raise ValueError("CREATIVE_COHORT_RECOVERY_TYPE_MISMATCH")
            work = request.work_input
            target = self.targets.get(work.source.source_id)
            if target is None:
                raise ValueError("CREATIVE_COHORT_RECOVERY_TARGET_NOT_ADMITTED")
        selected = self.prepare(target)  # exact source/plan pins and current real owner rights
        if selected.workflow_id != workflow_id:
            with self.sessions() as session:
                predecessor = session.get(WorkflowInstanceRecord, workflow_id)
                if predecessor is None or (
                    resolve_external_item_learning_recovery(session, predecessor).workflow_id
                    != selected.workflow_id
                ):
                    raise ValueError("CREATIVE_COHORT_RECOVERY_WORKFLOW_NOT_ADMITTED")
            return selected  # an already recorded successor is an idempotent replay
        with self.sessions.begin() as session:
            definition = admitted_workflow_definition(
                session,
                definition_key="external-item-learning",
                definition_version=self.scope.workflow_definition_version,
            )
            preset_row = session.get(
                ExecutionPresetRevisionRecord, self.scope.extraction_preset.preset_revision_id
            )
            preset = validated_preset(preset_row) if preset_row else None
            if (
                definition is None
                or definition.definition_hash != self.scope.workflow_definition_sha256
                or not isinstance(preset, ExecutionPresetRevision)
                or preset.content_sha256 != self.scope.extraction_preset.sha256
            ):
                raise ValueError("CREATIVE_COHORT_PREPARATION_POLICY_MISMATCH")
            recovered = prepare_unstarted_external_item_learning_recovery(
                session,
                predecessor_workflow_id=workflow_id,
                definition=definition,
                work=work,
                operator_id=self.cohort.requested_by_operator_id,
                source_authorizer=self.source,
                page_publisher=self.pages,
                expected_preset=preset,
            )
            return recovered.selection

    def _ensure_preview(self, target: CreativeCohortTarget) -> None:
        # Reauthorize before asking the real Catalog owner to materialize bytes.
        from eom_catalog_service.external_creative_learning_source import (
            authorize_external_creative_learning_claim,
        )
        from eom_catalog_service.external_creative_learning_targets import (
            get_external_creative_learning_target,
        )

        with self.sessions() as session:
            authorize_external_creative_learning_claim(
                session, self.cohort.requested_by_operator_id
            )
            current = get_external_creative_learning_target(
                session, import_id=self.cohort.import_id, external_number=target.external_number
            )
            if any(
                getattr(current, field) != getattr(target, field)
                for field in (
                    "source_id",
                    "source_revision_id",
                    "observation_sha256",
                    "selected_edition",
                )
            ):
                raise ValueError("CREATIVE_COHORT_SOURCE_MISMATCH")
        query = ExternalItemDocumentMediaQuery(
            source_id=target.source_id,
            source_revision_id=target.source_revision_id,
            edition=target.selected_edition,
        )
        try:
            preview = self.preview.open(query)
        except ExternalItemPreviewUnavailable as error:
            if error.code != "EXTERNAL_ITEM_PREVIEW_NOT_READY":
                raise
            prepare_creative_preview(query)
        else:
            preview.member.stream.close()
