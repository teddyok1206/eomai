"""Reuse the existing single owner and immutable file-set publication boundary."""

from __future__ import annotations

import re
from pathlib import Path

from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.inference_transfer_experiment_execution import (
    InferenceTransferExperimentExecution,
)
from eom_orchestrator.inference_transfer_experiment_ports import (
    CpuExperimentRunPort,
    LocalExperimentPublication,
    PublishedExperimentResult,
)
from eom_orchestrator.inference_transfer_experiment_workspace import (
    MAX_EXPERIMENT_MEMBER_BYTES,
    RESULT_SCHEMA,
    ProtectedExperimentWorkspace,
)
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadPort


class InferenceTransferExperimentArtifactStore:
    """No new DB ownership; the supplied publisher remains the only NAS committer."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ValueError("installed source identity is required")
        self.publisher = publisher
        self.source_commit = source_commit

    def publish(self, prepared: LocalExperimentPublication) -> PublishedExperimentResult:
        if (
            re.fullmatch(r"embeddingexecution_[0-9a-f]{32}", prepared.execution_id) is None
            or type(prepared.member_bytes) is not int
            or not 0 < prepared.member_bytes <= MAX_EXPERIMENT_MEMBER_BYTES
        ):
            raise ValueError("experiment publication identity or budget is invalid")
        receipt = self.publisher.publish(
            members=(
                ControlFileSetMember(
                    file_name="result.json",
                    source=prepared.source,
                    sha256=prepared.member_sha256,
                    bytes=prepared.member_bytes,
                    schema_ref=RESULT_SCHEMA,
                    media_type="application/json",
                ),
            ),
            primary_file="result.json",
            artifact_type="control_inference_transfer_experiment",
            manifest_version="control-file-set/1.0",
            idempotency_key="inference-transfer-experiment:"
            + prepared.execution_id.removeprefix("embeddingexecution_"),
            source_commit=self.source_commit,
            created_at=prepared.created_at,
        )
        if (
            receipt.primary_file != "result.json"
            or receipt.primary_sha256 != prepared.member_sha256
        ):
            raise ValueError("existing owner receipt differs from the validated result member")
        return PublishedExperimentResult(
            job_id=receipt.job_id,
            result=ArtifactMemberPointer(
                artifact_id=receipt.artifact_id,
                artifact_revision_id=receipt.artifact_revision_id,
                member_path="result.json",
                schema_ref=RESULT_SCHEMA,
                media_type="application/json",
                sha256=receipt.primary_sha256,
            ),
            manifest_sha256=receipt.manifest_sha256,
        )


def compose_inference_transfer_experiment(
    *,
    snapshot: SnapshotReadPort,
    cpu: CpuExperimentRunPort | None,
    publisher: ControlFileSetPublisher | None,
    workspace_root: Path,
    source_commit: str,
) -> InferenceTransferExperimentExecution:
    """Compose supplied supported owners; do not create auth/runtime/DB access.

    Snapshot transport retains the actual caller's credentials. An installed
    isolated CPU launch adapter must be supplied independently; absence never
    selects the ambient interpreter or silently enables a source-only runner.
    """
    return InferenceTransferExperimentExecution(
        snapshot=snapshot,
        workspace=ProtectedExperimentWorkspace(workspace_root),
        cpu=cpu,
        commit=None
        if publisher is None
        else InferenceTransferExperimentArtifactStore(publisher, source_commit=source_commit),
    )
