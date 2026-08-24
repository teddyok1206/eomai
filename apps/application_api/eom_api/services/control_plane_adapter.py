"""Application and read-model adapter for the Codex execution control plane."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Never

from eom_api_contracts.control_plane import (
    CodexAccountCommandRequest,
    CodexAccountView,
    CodexCapabilityView,
    CodexControlCommandView,
    CreateExecutionPresetDraftRequest,
    ExecutionPresetEvaluationView,
    ExecutionPresetRevisionView,
    ExecutionPresetView,
    PresetRolePolicyInput,
)
from eom_operator_identity import ActorContext
from eom_orchestrator.control_commands import (
    build_codex_control_command,
    enqueue_codex_control_command,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexCapabilityEntryRecord,
    CodexCapabilitySnapshotRecord,
    CodexControlCommandRecord,
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import JobRecord
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    create_execution_preset_draft_v2,
    deprecate_execution_preset,
    release_execution_preset,
)
from sqlalchemy import Engine, func, select

from eom_api.errors import ApiError


class ControlPlaneAdapter:
    """Keep HTTP presentation outside immutable lifecycle and queue transactions."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def list_accounts(self) -> tuple[CodexAccountView, ...]:
        with self.sessions() as session:
            bindings = tuple(
                session.scalars(
                    select(CodexAuthBindingRecord).order_by(
                        CodexAuthBindingRecord.worker_slot_id,
                        CodexAuthBindingRecord.binding_id,
                    )
                )
            )
            if not bindings:
                return ()
            binding_ids = [row.binding_id for row in bindings]
            ranked_snapshots = (
                select(
                    CodexCapabilitySnapshotRecord.capability_snapshot_id.label("snapshot_id"),
                    CodexCapabilitySnapshotRecord.binding_id.label("binding_id"),
                    func.row_number()
                    .over(
                        partition_by=CodexCapabilitySnapshotRecord.binding_id,
                        order_by=(
                            CodexCapabilitySnapshotRecord.observed_at.desc(),
                            CodexCapabilitySnapshotRecord.capability_snapshot_id.desc(),
                        ),
                    )
                    .label("rank"),
                )
                .where(CodexCapabilitySnapshotRecord.binding_id.in_(binding_ids))
                .subquery()
            )
            latest: dict[str, str] = {
                binding_id: snapshot_id
                for binding_id, snapshot_id in session.execute(
                    select(ranked_snapshots.c.binding_id, ranked_snapshots.c.snapshot_id).where(
                        ranked_snapshots.c.rank == 1
                    )
                ).all()
            }
            snapshot_ids = tuple(latest.values())
            capabilities: dict[str, list[CodexCapabilityView]] = defaultdict(list)
            if snapshot_ids:
                for entry in session.scalars(
                    select(CodexCapabilityEntryRecord)
                    .where(CodexCapabilityEntryRecord.capability_snapshot_id.in_(snapshot_ids))
                    .order_by(
                        CodexCapabilityEntryRecord.model,
                        CodexCapabilityEntryRecord.reasoning_effort,
                    )
                ):
                    capabilities[entry.capability_snapshot_id].append(
                        CodexCapabilityView(
                            model=entry.model,
                            reasoning_effort=entry.reasoning_effort,
                            state=entry.state,
                        )
                    )
            lease_counts: dict[str, int] = {
                binding_id: count
                for binding_id, count in session.execute(
                    select(WorkerLeaseRecord.binding_id, func.count(WorkerLeaseRecord.lease_id))
                    .where(
                        WorkerLeaseRecord.binding_id.in_(binding_ids),
                        WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                    )
                    .group_by(WorkerLeaseRecord.binding_id)
                ).all()
            }
            slot_ids = [row.worker_slot_id for row in bindings]
            ranked_jobs = (
                select(
                    JobRecord.job_id.label("job_id"),
                    JobRecord.worker_slot_id.label("slot_id"),
                    func.row_number()
                    .over(
                        partition_by=JobRecord.worker_slot_id,
                        order_by=(JobRecord.completed_at.desc(), JobRecord.job_id.desc()),
                    )
                    .label("rank"),
                )
                .where(
                    JobRecord.worker_slot_id.in_(slot_ids),
                    JobRecord.status == "SUCCEEDED",
                )
                .subquery()
            )
            last_jobs: dict[str, str] = {
                slot_id: job_id
                for slot_id, job_id in session.execute(
                    select(ranked_jobs.c.slot_id, ranked_jobs.c.job_id).where(
                        ranked_jobs.c.rank == 1
                    )
                ).all()
            }
            return tuple(
                self._account(
                    binding,
                    capabilities=tuple(capabilities.get(latest.get(binding.binding_id, ""), [])),
                    active_lease_count=int(lease_counts.get(binding.binding_id, 0)),
                    last_successful_job_id=last_jobs.get(binding.worker_slot_id),
                )
                for binding in bindings
            )

    def account(self, binding_id: str) -> CodexAccountView:
        matches = [value for value in self.list_accounts() if value.binding_id == binding_id]
        if len(matches) != 1:
            self._not_found("CODEX_ACCOUNT_NOT_FOUND")
        return matches[0]

    def enqueue_account_command(
        self,
        *,
        binding_id: str,
        body: CodexAccountCommandRequest,
        actor: ActorContext,
        expected_version: int,
        idempotency_key: str,
    ) -> CodexControlCommandView:
        document = build_codex_control_command(
            command_type=body.command_type,
            binding_id=binding_id,
            expected_resource_version=expected_version,
            requested_by_operator_id=actor.actor_id,
            requested_at=datetime.now(UTC),
            reason_code=body.reason_code,
        )
        try:
            with transaction(self.sessions) as session:
                row = enqueue_codex_control_command(
                    session,
                    document=document,
                    idempotency_key=idempotency_key,
                )
                return self._command(row)
        except ControlPlaneError as exc:
            self._map_error(exc)

    def control_command(self, command_id: str) -> CodexControlCommandView:
        with self.sessions() as session:
            row = session.get(CodexControlCommandRecord, command_id)
            if row is None:
                self._not_found("CODEX_CONTROL_COMMAND_NOT_FOUND")
            return self._command(row)

    def list_presets(self) -> tuple[ExecutionPresetView, ...]:
        with self.sessions() as session:
            logicals = tuple(
                session.scalars(
                    select(ExecutionPresetRecord).order_by(
                        ExecutionPresetRecord.preset_key, ExecutionPresetRecord.preset_id
                    )
                )
            )
            preset_ids = [row.preset_id for row in logicals]
            revisions_by_preset: dict[str, list[ExecutionPresetRevisionRecord]] = defaultdict(list)
            if preset_ids:
                for revision in session.scalars(
                    select(ExecutionPresetRevisionRecord)
                    .where(ExecutionPresetRevisionRecord.preset_id.in_(preset_ids))
                    .order_by(
                        ExecutionPresetRevisionRecord.preset_id,
                        ExecutionPresetRevisionRecord.revision_number,
                    )
                ):
                    revisions_by_preset[revision.preset_id].append(revision)
            revision_ids = [
                revision.preset_revision_id
                for values in revisions_by_preset.values()
                for revision in values
            ]
            evaluations_by_revision: dict[str, list[ExecutionPresetEvaluationRecord]] = defaultdict(
                list
            )
            if revision_ids:
                for evaluation in session.scalars(
                    select(ExecutionPresetEvaluationRecord)
                    .where(
                        ExecutionPresetEvaluationRecord.evaluated_preset_revision_id.in_(
                            revision_ids
                        )
                    )
                    .order_by(
                        ExecutionPresetEvaluationRecord.completed_at,
                        ExecutionPresetEvaluationRecord.evaluation_id,
                    )
                ):
                    evaluations_by_revision[evaluation.evaluated_preset_revision_id].append(
                        evaluation
                    )
            return tuple(
                ExecutionPresetView(
                    preset_id=logical.preset_id,
                    preset_key=logical.preset_key,
                    current_revision_id=logical.current_revision_id,
                    state=logical.state,
                    created_at=logical.created_at,
                    updated_at=logical.updated_at,
                    revisions=tuple(
                        self._preset_revision(
                            revision,
                            evaluations_by_revision[revision.preset_revision_id],
                        )
                        for revision in revisions_by_preset[logical.preset_id]
                    ),
                )
                for logical in logicals
            )

    def preset(self, preset_id: str) -> ExecutionPresetView:
        matches = [value for value in self.list_presets() if value.preset_id == preset_id]
        if len(matches) != 1:
            self._not_found("EXECUTION_PRESET_NOT_FOUND")
        return matches[0]

    def create_preset_draft(
        self, *, body: CreateExecutionPresetDraftRequest, actor: ActorContext
    ) -> ExecutionPresetRevisionView:
        try:
            with transaction(self.sessions) as session:
                role_policies = [
                    item.model_dump(mode="json", exclude_none=True) for item in body.role_policies
                ]
                if body.retrieval_policy is not None:
                    row = create_execution_preset_draft_v2(
                        session,
                        preset_key=body.preset_key,
                        display_name=body.display_name,
                        description=body.description,
                        role_policies=role_policies,
                        capacity_policy_revision_id=body.capacity_policy_revision_id,
                        general_knowledge_policy=body.general_knowledge_policy,
                        compatible_workflow_protocols=list(body.compatible_workflow_protocols),
                        retrieval_policy=body.retrieval_policy.model_dump(mode="json"),
                        created_by=actor.actor_id,
                        created_at=datetime.now(UTC),
                    )
                else:
                    row = create_execution_preset_draft(
                        session,
                        preset_key=body.preset_key,
                        display_name=body.display_name,
                        description=body.description,
                        role_policies=role_policies,
                        capacity_policy_revision_id=body.capacity_policy_revision_id,
                        general_knowledge_policy=body.general_knowledge_policy,
                        compatible_workflow_protocols=list(body.compatible_workflow_protocols),
                        created_by=actor.actor_id,
                        created_at=datetime.now(UTC),
                    )
                return self._preset_revision(row, ())
        except ControlPlaneError as exc:
            self._map_error(exc)

    def release_preset(
        self,
        *,
        draft_revision_id: str,
        actor: ActorContext,
        expected_version: int,
    ) -> ExecutionPresetRevisionView:
        try:
            with transaction(self.sessions) as session:
                draft = session.get(ExecutionPresetRevisionRecord, draft_revision_id)
                if draft is None:
                    self._not_found("EXECUTION_PRESET_REVISION_NOT_FOUND")
                if draft.revision_number != expected_version:
                    self._version_mismatch()
                row = release_execution_preset(
                    session,
                    draft_revision_id=draft_revision_id,
                    released_by=actor.actor_id,
                    released_at=datetime.now(UTC),
                )
                evaluations = tuple(
                    session.scalars(
                        select(ExecutionPresetEvaluationRecord).where(
                            ExecutionPresetEvaluationRecord.evaluated_policy_sha256
                            == _policy_hash(row)
                        )
                    )
                )
                return self._preset_revision(row, evaluations)
        except ControlPlaneError as exc:
            self._map_error(exc)

    def deprecate_preset(
        self, *, preset_id: str, actor: ActorContext, expected_version: int
    ) -> ExecutionPresetRevisionView:
        try:
            with transaction(self.sessions) as session:
                logical = session.get(ExecutionPresetRecord, preset_id)
                current = (
                    session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
                    if logical is not None and logical.current_revision_id is not None
                    else None
                )
                if logical is None or current is None:
                    self._not_found("EXECUTION_PRESET_NOT_FOUND")
                if current.revision_number != expected_version:
                    self._version_mismatch()
                row = deprecate_execution_preset(
                    session,
                    preset_id=preset_id,
                    deprecated_by=actor.actor_id,
                    deprecated_at=datetime.now(UTC),
                )
                return self._preset_revision(row, ())
        except ControlPlaneError as exc:
            self._map_error(exc)

    @staticmethod
    def _account(
        row: CodexAuthBindingRecord,
        *,
        capabilities: tuple[CodexCapabilityView, ...],
        active_lease_count: int,
        last_successful_job_id: str | None,
    ) -> CodexAccountView:
        return CodexAccountView(
            binding_id=row.binding_id,
            slot_key=f"slot{row.worker_slot_id}",
            account_label=row.account_label,
            state=row.state,
            reason_code=row.reason_code,
            codex_cli_version=row.codex_cli_version,
            observed_at=row.observed_at,
            valid_until=row.valid_until,
            resource_version=row.resource_version,
            capabilities=capabilities,
            active_lease_count=active_lease_count,
            last_successful_job_id=last_successful_job_id,
        )

    @staticmethod
    def _command(row: CodexControlCommandRecord) -> CodexControlCommandView:
        return CodexControlCommandView(
            command_id=row.command_id,
            command_type=row.command_type,
            binding_id=row.binding_id,
            state=row.state,
            attempts=row.attempts,
            result_resource_version=row.result_resource_version,
            error_code=row.error_code,
            requested_at=row.requested_at,
            processed_at=row.processed_at,
        )

    @staticmethod
    def _preset_revision(
        row: ExecutionPresetRevisionRecord,
        evaluations: tuple[ExecutionPresetEvaluationRecord, ...]
        | list[ExecutionPresetEvaluationRecord],
    ) -> ExecutionPresetRevisionView:
        return ExecutionPresetRevisionView(
            schema_version=row.schema_version,
            preset_revision_id=row.preset_revision_id,
            preset_id=row.preset_id,
            revision_number=row.revision_number,
            state=row.state,
            display_name=row.display_name,
            description=row.description,
            capacity_policy_revision_id=row.capacity_policy_revision_id,
            general_knowledge_policy=row.general_knowledge_policy,
            compatible_workflow_protocols=tuple(row.compatible_workflow_protocols),
            content_sha256=row.content_sha256,
            created_at=row.created_at,
            role_policies=tuple(
                PresetRolePolicyInput.model_validate(item)
                for item in row.canonical_document["role_policies"]
            ),
            retrieval_policy=row.canonical_document.get("retrieval_policy"),
            evaluations=tuple(
                ExecutionPresetEvaluationView(
                    evaluation_id=item.evaluation_id,
                    evaluated_preset_revision_id=item.evaluated_preset_revision_id,
                    evaluated_policy_sha256=item.evaluated_policy_sha256,
                    scope=item.scope,
                    outcome=item.outcome,
                    summary_code=item.summary_code,
                    cases_total=item.cases_total,
                    cases_passed=item.cases_passed,
                    quality_score_permille=item.quality_score_permille,
                    report_artifact_id=item.report_artifact_id,
                    report_artifact_revision_id=item.report_artifact_revision_id,
                    report_content_sha256=item.report_content_sha256,
                    completed_at=item.completed_at,
                )
                for item in evaluations
            ),
        )

    @staticmethod
    def _not_found(code: str) -> Never:
        raise ApiError(
            404, code, "Control-plane resource not found", "The resource does not exist."
        )

    @staticmethod
    def _version_mismatch() -> Never:
        raise ApiError(
            412,
            "API_RESOURCE_VERSION_MISMATCH",
            "Resource version mismatch",
            "Refresh the resource before retrying the command.",
        )

    @staticmethod
    def _map_error(exc: ControlPlaneError) -> Never:
        conflict_codes = {
            "CONTROL_IDEMPOTENCY_CONFLICT",
            "CONTROL_RESOURCE_VERSION_CONFLICT",
            "CONTROL_REVISION_CONFLICT",
            "CONTROL_PRESET_RETIRED",
            "CONTROL_PRESET_EVALUATION_REQUIRED",
        }
        status = 409 if exc.code in conflict_codes else 422
        raise ApiError(
            status,
            exc.code,
            "Control-plane command rejected",
            "The requested control-plane transition failed its validated contract.",
        ) from exc


def _policy_hash(row: ExecutionPresetRevisionRecord) -> str:
    from eom_orchestrator.preset_lifecycle import execution_preset_policy_sha256

    return execution_preset_policy_sha256(row.canonical_document)
