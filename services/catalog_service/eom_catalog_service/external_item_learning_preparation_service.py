"""Authenticated source→page→control→READY preparation; never START a worker."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict
from uuid import NAMESPACE_URL, uuid5

from eom_api_contracts.external_item_learning_start import ExternalItemLearningStartV1
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_identifiers import content_sha256, sha256_bytes
from eom_operator_identity import ActorContext
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, resolve_released_instruction_bundle
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.external_item_learning_page_publication import (
    external_item_learning_page_artifact,
    publish_external_item_learning_pages,
)
from eom_orchestrator.external_item_learning_page_render import (
    PdfToolRunner,
    render_external_item_learning_pages,
)
from eom_orchestrator.external_item_learning_policy_preparation import (
    ExternalItemLearningControlInputs,
    prepare_external_item_learning_execution_policy,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.preset_model_selection import validated_preset
from eom_orchestrator.settings import Settings
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.models import ExternalItemLearningWorkerRequest, WorkflowRequest
from eom_workflow_runner.external_item_learning_preparation import (
    PreparedExternalItemLearning,
    prepare_external_item_learning_workflow,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    admitted_workflow_definition,
    load_persisted_workflow_request,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.external_creative_learning_source import (
    CatalogExternalItemLearningSourceAuthorizer,
    ExternalCreativeLearningSourceError,
    authorize_external_creative_learning_preparation,
    read_external_creative_learning_input,
    resolve_external_creative_learning_source,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
)


@dataclass(frozen=True, slots=True)
class PrepareExternalItemLearningCommand:
    selection: ExternalItemLearningStartV1
    controls: ExternalItemLearningControlInputs
    idempotency_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.idempotency_key, str)
            or not 1 <= len(self.idempotency_key) <= 128
            or any(ord(character) < 0x20 for character in self.idempotency_key)
        ):
            raise ValueError("creative preparation key is invalid")


@dataclass(frozen=True, slots=True)
class CreativeMaterializationCheck:
    plan_sha256: str
    agents_sha256: str
    invocation_sha256: str
    image_input_manifest_sha256: str | None
    member_count: int
    total_bytes: int


class _CreativeSourceArguments(TypedDict):
    import_id: str
    external_number: str
    expected_source_revision_id: str
    expected_observation_sha256: str
    expected_edition: int


@dataclass(frozen=True, slots=True)
class PreparedExternalItemLearningSource:
    external_number: str
    work_input_sha256: str
    workflow: PreparedExternalItemLearning
    materialization: CreativeMaterializationCheck


class ExternalItemLearningPreparationService:
    """Use the existing owners; the actor provider comes from actual Identity authentication."""

    def __init__(
        self,
        engine: Engine,
        *,
        settings: Settings,
        actor_provider: Callable[[], ActorContext],
        worker_group_id: int,
        preview: ExternalItemPreviewProjectionService | None = None,
        pdf_tools: PdfToolRunner | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self.actor_provider = actor_provider
        self.worker_group_id = worker_group_id
        self.preview = preview or ExternalItemPreviewProjectionService(engine)
        self.source_authorizer = CatalogExternalItemLearningSourceAuthorizer(self.preview)
        self.pages = ControlFileSetPublisher(engine, settings)
        self.controls = ControlArtifactPublisher(engine, settings)
        self.pdf_tools = pdf_tools

    def _operator(self) -> str:
        actor = self.actor_provider()
        with self.sessions.begin() as session:
            return authorize_external_creative_learning_preparation(session, actor)

    def _authorize_owner(self, operator_id: str) -> None:
        if self._operator() != operator_id:
            raise ExternalCreativeLearningSourceError("EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED")

    @staticmethod
    def _source_arguments(selection: ExternalItemLearningStartV1) -> _CreativeSourceArguments:
        return {
            "import_id": selection.import_id,
            "external_number": selection.external_number,
            "expected_source_revision_id": selection.source_revision_id,
            "expected_observation_sha256": selection.observation_sha256,
            "expected_edition": selection.selected_edition,
        }

    def prepare(
        self, command: PrepareExternalItemLearningCommand
    ) -> PreparedExternalItemLearningSource:
        selection = ExternalItemLearningStartV1.model_validate(
            command.selection.model_dump(mode="json")
        )
        operator = self._operator()
        key = (
            "creative-prepare:"
            + content_sha256({"operator_id": operator, "idempotency_key": command.idempotency_key})[
                7:
            ]
        )
        root = self.settings.staging_root
        if not root.is_dir() or root.is_symlink() or root.resolve() != root:
            raise ValueError("creative local staging root is unavailable")
        with self.sessions() as session:
            existing = session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            if existing is not None:
                work, preset = self._existing_input(session, existing, operator, command)
            else:
                work, preset = None, None
        with TemporaryDirectory(prefix="creative-prepare-", dir=root) as temporary:
            local = Path(temporary)
            if work is None:
                with self.sessions.begin() as session:
                    source = read_external_creative_learning_input(
                        session,
                        self.preview,
                        actor=self.actor_provider(),
                        **self._source_arguments(selection),
                    )
                policy = prepare_external_item_learning_execution_policy(
                    self.sessions,
                    self.controls,
                    inputs=command.controls,
                    operator_id=operator,
                    authorize_control_change=self._authorize_owner,
                )
                preset = policy.preset
                if self.pdf_tools is None:
                    rendered = render_external_item_learning_pages(
                        source.source, source.pdf_bytes, workspace=local / "rendered"
                    )
                else:
                    rendered = render_external_item_learning_pages(
                        source.source,
                        source.pdf_bytes,
                        workspace=local / "rendered",
                        run=self.pdf_tools,
                    )
                self._authorize_owner(operator)
                artifact = publish_external_item_learning_pages(
                    self.pages, rendered, source_commit=command.controls.source_commit
                )
                value = {
                    "schema_version": "external-item-learning-work-input/1.0",
                    "request_id": "extlearnreq_" + uuid5(NAMESPACE_URL, key).hex,
                    "source": source.source.model_dump(mode="json"),
                    "page_set": rendered.manifest.model_dump(mode="json"),
                    "page_artifact": external_item_learning_page_artifact(artifact).model_dump(
                        mode="json"
                    ),
                }
                work = ExternalItemLearningWorkInput.model_validate(
                    {**value, "request_sha256": content_sha256(value)}
                )
            self._authorize_owner(operator)
            if preset is None:
                raise ControlPlaneError(
                    "CONTROL_PLAN_MISSING", "creative released preset is missing"
                )
            with self.sessions.begin() as session:
                definition = admitted_workflow_definition(
                    session, definition_key="external-item-learning", definition_version="1.0.0"
                )
                if (
                    definition is None
                    or definition.definition_hash != command.controls.definition.sha256
                ):
                    raise ControlPlaneError(
                        "CONTROL_WORKFLOW_NOT_PUBLISHED", "creative definition differs"
                    )
                prepared = prepare_external_item_learning_workflow(
                    session,
                    definition=definition,
                    work=work,
                    operator_id=operator,
                    idempotency_key=key,
                    source_authorizer=self.source_authorizer,
                    page_publisher=self.pages,
                    expected_preset=preset,
                )
                self._authorize_owner(operator)
            workspace = local / "worker-staging"
            workspace.mkdir()
            os.chown(workspace, -1, self.worker_group_id)
            workspace.chmod(0o2770)
            with self.sessions.begin() as session:
                allowed = authorized_execution_artifact_revisions(
                    session, plan_id=prepared.selection.plan_id, step_key="extract"
                )
                materialized = materialize_execution_step(
                    session,
                    plan_id=prepared.selection.plan_id,
                    step_key="extract",
                    workspace=workspace,
                    canonical_artifact_root=self.settings.nas_artifact_root,
                    worker_group_id=self.worker_group_id,
                    authorized_artifact_revision_ids=allowed,
                    creative_page_publisher=self.pages,
                )
                if (
                    materialized.plan_id != prepared.selection.plan_id
                    or materialized.plan_sha256 != prepared.selection.plan_sha256
                    or materialized.image_input_manifest_sha256 is None
                ):
                    raise ControlPlaneError(
                        "CONTROL_PLAN_HASH_MISMATCH", "creative staging differs"
                    )
            self._authorize_owner(operator)
            with self.sessions.begin() as session:
                current = resolve_external_creative_learning_source(
                    session,
                    self.preview,
                    actor=self.actor_provider(),
                    **self._source_arguments(selection),
                )
                if current != work.source:
                    raise ValueError("creative source changed during preparation")
                workflow = session.get(
                    WorkflowInstanceRecord,
                    prepared.selection.workflow_id,
                    with_for_update=True,
                    populate_existing=True,
                )
                step = session.get(
                    WorkflowStepRunRecord,
                    prepared.selection.step_run_id,
                    with_for_update=True,
                    populate_existing=True,
                )
                if (
                    workflow is None
                    or workflow.state != "REQUESTED"
                    or step is None
                    or step.workflow_id != workflow.workflow_id
                    or step.state != "READY"
                    or step.platform_job_id is not None
                    or session.scalar(
                        select(WorkflowCommandRecord.command_id)
                        .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
                        .limit(1)
                    )
                    is not None
                ):
                    raise ValueError("creative preparation was concurrently scheduled")
            return PreparedExternalItemLearningSource(
                selection.external_number,
                work.request_sha256,
                prepared,
                CreativeMaterializationCheck(
                    materialized.plan_sha256,
                    materialized.agents_sha256,
                    materialized.invocation_sha256,
                    materialized.image_input_manifest_sha256,
                    materialized.materialized_member_count,
                    materialized.materialized_bytes,
                ),
            )

    def _existing_input(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord,
        operator: str,
        command: PrepareExternalItemLearningCommand,
    ) -> tuple[ExternalItemLearningWorkInput, ExecutionPresetRevision]:
        request = load_persisted_workflow_request(workflow.initial_request)
        if not isinstance(request, WorkflowRequest):
            raise ValueError("creative stored request type differs")
        if (
            workflow.created_actor_type != "human"
            or workflow.created_actor_id != operator
            or request.request_name != "EXTERNAL_ITEM_LEARNING_REQUEST"
            or workflow.definition_hash != command.controls.definition.sha256
            or request.external_item_learning_work is None
        ):
            raise ValueError("creative preparation identity conflicts")
        work = request.external_item_learning_work
        selection = command.selection
        if (
            work.source.import_id,
            work.source.external_number,
            work.source.source_revision_id,
            work.source.observation_sha256,
            work.source.selected_edition,
        ) != (
            selection.import_id,
            selection.external_number,
            selection.source_revision_id,
            selection.observation_sha256,
            selection.selected_edition,
        ):
            raise ValueError("creative source selection conflicts")
        plan = validate_external_item_learning_execution_plan(
            session.scalar(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
                )
            ),
            workflow_id=workflow.workflow_id,
            step_key="extract",
            request=ExternalItemLearningWorkerRequest(work_input=work),
        )
        row = session.get(ExecutionPresetRevisionRecord, plan.preset_revision_id)
        preset = validated_preset(row) if row is not None else None
        instruction = resolve_released_instruction_bundle(session, plan.steps[0].instruction_bundle)
        if (
            not isinstance(preset, ExecutionPresetRevision)
            or preset.state != "RELEASED"
            or preset.content_sha256 != plan.preset_sha256
            or plan.capacity_policy_revision_id != command.controls.capacity_revision_id
            or plan.steps[0].model != command.controls.candidate.model
            or plan.steps[0].reasoning_effort != command.controls.candidate.reasoning_effort
            or instruction.created_at != command.controls.reviewed_at
            or tuple(part.artifact.sha256 for part in instruction.components)
            != (
                sha256_bytes(command.controls.platform_payload),
                sha256_bytes(command.controls.role_payload),
            )
        ):
            raise ValueError("creative preparation policy conflicts")
        return work, preset
