"""Snapshot → protected CPU handoff → validated result → current owner commit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eom_catalog_contracts.models import Sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import TypeAdapter

from eom_orchestrator.inference_transfer_experiment_ports import (
    CpuExperimentRunError,
    CpuExperimentRunPort,
    ExperimentResultCommitPort,
    PublishedExperimentResult,
)
from eom_orchestrator.inference_transfer_experiment_workspace import (
    RESULT_SCHEMA,
    ExperimentWorkspaceError,
    ProtectedExperimentWorkspace,
)
from eom_orchestrator.inference_transfer_snapshot_staging import (
    AuthenticatedSnapshotActor,
    SnapshotExperimentStageCommand,
    SnapshotReadPort,
    reauthorize_staged_experiment,
    stage_snapshot_experiment,
)


class ExperimentExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CommittedInferenceTransferExperiment:
    execution_id: str
    request_sha256: str
    result_sha256: str
    published: PublishedExperimentResult
    cpu_launch_count: int


class InferenceTransferExperimentExecution:
    def __init__(
        self,
        *,
        snapshot: SnapshotReadPort,
        workspace: ProtectedExperimentWorkspace,
        cpu: CpuExperimentRunPort | None,
        commit: ExperimentResultCommitPort | None,
    ) -> None:
        self.snapshot = snapshot
        self.workspace = workspace
        self.cpu = cpu
        self.commit = commit

    def execute(
        self,
        actor: AuthenticatedSnapshotActor,
        command: SnapshotExperimentStageCommand,
        *,
        execution_id: str,
        created_at: datetime,
    ) -> CommittedInferenceTransferExperiment:
        if self.cpu is None or self.commit is None:
            raise ExperimentExecutionError("INFERENCE_EXPERIMENT_EXECUTION_UNAVAILABLE")
        staged = stage_snapshot_experiment(actor, command, self.snapshot)
        local = self.workspace.prepare(
            staged.request, execution_id=execution_id, created_at=created_at
        )
        state = self.workspace.state(local)
        if state in {"KNOWN_FAILED", "UNCERTAIN"}:
            raise ExperimentExecutionError("INFERENCE_EXPERIMENT_EXECUTION_" + state)
        launches = 0
        if state == "NOT_STARTED":
            self.workspace.claim(local, staged.request)
            launches = 1
            try:
                self.cpu.run(local)
            except CpuExperimentRunError as exc:
                if exc.outcome == "KNOWN_FAILED":
                    self.workspace.failed(local)
                raise ExperimentExecutionError(
                    "INFERENCE_EXPERIMENT_EXECUTION_" + exc.outcome
                ) from exc
            except Exception as exc:
                # Preserve the launch observation. Unknown termination is never
                # interpreted as permission to call the model a second time.
                raise ExperimentExecutionError("INFERENCE_EXPERIMENT_EXECUTION_UNCERTAIN") from exc
        try:
            result, publication = self.workspace.validate_result(
                local, staged.request, completed=state == "COMPLETED"
            )
        except (ValueError, OSError, SchemaValidationError, ExperimentWorkspaceError) as exc:
            if state == "NOT_STARTED":
                self.workspace.failed(local)
            raise ExperimentExecutionError("INFERENCE_EXPERIMENT_RESULT_INVALID") from exc
        # No cached receipt or successful CPU output substitutes for this current
        # full-population read. Publisher retry must cross it again as well.
        reauthorize_staged_experiment(actor, staged, self.snapshot)
        try:
            published = self.commit.publish(publication)
        except Exception as exc:
            # Owner publication may already have crossed its durable boundary.
            # Keep the completed input/output and existing owner key for replay;
            # neither assume no commit nor launch the CPU again.
            raise ExperimentExecutionError("INFERENCE_EXPERIMENT_COMMIT_UNCERTAIN") from exc
        try:
            pointer = ArtifactMemberPointer.model_validate(published.result.model_dump(mode="json"))
            TypeAdapter(Sha256).validate_python(published.manifest_sha256)
            TypeAdapter(JobId).validate_python(published.job_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ExperimentExecutionError("INFERENCE_EXPERIMENT_COMMIT_RECEIPT_INVALID") from exc
        if (
            pointer.member_path != "result.json"
            or pointer.schema_ref != RESULT_SCHEMA
            or pointer.media_type != "application/json"
            or pointer.sha256 != publication.member_sha256
        ):
            raise ExperimentExecutionError("INFERENCE_EXPERIMENT_COMMIT_RECEIPT_INVALID")
        return CommittedInferenceTransferExperiment(
            execution_id, staged.request.request_sha256, result.result_sha256, published, launches
        )
