"""Synthetic human-owner ports; never credentials, live permissions or NAS evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from eom_api_contracts.auth import CurrentOperator
from eom_catalog_contracts.inference_transfer_human_review import (
    InferenceTransferHumanBundleCommand,
    InferenceTransferHumanRecordCommand,
    InferenceTransferHumanReviewBundle,
    InferenceTransferHumanReviewRecord,
)
from eom_catalog_contracts.inference_transfer_invocation import (
    TRANSFER_RESULT_MEMBER_SCHEMA,
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.item_inference_transfer import HumanTransferEvaluation
from eom_identifiers import content_sha256
from eom_orchestrator.control_artifacts import PublishedControlArtifact
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_human_review import (
    AuthenticatedInferenceTransferHumanReviewOwner,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.control_plane import ControlArtifactPointer

from tests.unit.inference_transfer_fixtures import request as comparison_request
from tests.unit.inference_transfer_fixtures import result as comparison_result
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_read_result,
    snapshot_records,
)

NOW = datetime(2026, 10, 10, 18, tzinfo=UTC)
ACTOR = "operator_" + "a" * 32
SESSION = "apisession_" + "b" * 32
WORKFLOW = "workflow_" + "c" * 32
SOURCE_COMMIT = "d" * 40
REQUIRED_PERMISSIONS = (
    "content_intake:read",
    "item:read",
    "knowledge_analysis:read",
    "knowledge_graph:retrieve",
    "workflow:read",
)


def principal(**changes: Any) -> CurrentOperator:
    return CurrentOperator.model_validate(
        {
            "operator_id": ACTOR,
            "username": "guiadmin",
            "display_name": "합성 검토자",
            "roles": ("ADMIN",),
            "effective_permissions": REQUIRED_PERMISSIONS,
            "session_id": SESSION,
            "authenticated_at": NOW - timedelta(minutes=1),
            "access_expires_at": NOW + timedelta(minutes=20),
            "password_change_required": False,
        }
        | changes
    )


class PrincipalPort:
    def __init__(self) -> None:
        self.value = principal()
        self.calls = 0
        self.on_read: Callable[[int], None] | None = None

    def read(self) -> CurrentOperator:
        self.calls += 1
        if self.on_read is not None:
            self.on_read(self.calls)
        return self.value


class SnapshotPort:
    def __init__(self, *, width: int = 1) -> None:
        self.records = snapshot_records()
        self.prepare = snapshot_prepare(
            query_item_revision_ids=(),
            chunk_budget={"max_entries": width, "max_encoded_bytes": 3 * 1024**2},
        )
        self.prepared = snapshot_prepare_result(
            self.records,
            header=snapshot_header(self.records, prepare=self.prepare, actor_id=ACTOR),
        )
        self.calls: list[tuple[str, InferenceTransferSnapshotRequest]] = []
        self.on_execute: Callable[[InferenceTransferSnapshotRequest], None] | None = None
        self.transform: (
            Callable[
                [InferenceTransferSnapshotRequest, InferenceTransferSnapshotResult],
                InferenceTransferSnapshotResult,
            ]
            | None
        ) = None

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        self.calls.append((actor_id, request))
        if self.on_execute is not None:
            self.on_execute(request)
        if isinstance(request, InferenceTransferSnapshotReadRequest):
            by_base = {row.index_entry.base_analysis_run_id: row for row in self.records}
            rows = tuple(
                by_base[row.base_analysis_run_id] for row in request.selected_index_entries
            )
            value: InferenceTransferSnapshotResult = snapshot_read_result(
                rows, request=request, baselines=()
            )
        else:
            value = self.prepared
        return value if self.transform is None else self.transform(request, value)


class ComparisonPort:
    def __init__(self, selection: InferenceTransferPairSubmitRequest) -> None:
        self.calls: list[
            tuple[InferenceTransferWorkflowReadRequest, InferenceTransferPairSubmitRequest]
        ] = []
        self.failure: Exception | None = None
        self.on_read: Callable[[int], None] | None = None
        self.value = hashed(
            InferenceTransferWorkflowReadResult,
            "result_sha256",
            workflow_id=WORKFLOW,
            workflow_state="COMPLETED",
            resource_version=2,
            comparison=selection.comparison,
            graph_snapshot=selection.snapshot_prepare.graph_snapshot,
            access_policy_revision_id=selection.snapshot_prepare.access_policy_revision_id,
            access_policy_sha256=selection.snapshot_prepare.access_policy_sha256,
            result_state="MEMBER_VERIFIED",
            result_artifact=ArtifactMemberPointer(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                member_path="result.json",
                schema_ref=TRANSFER_RESULT_MEMBER_SCHEMA,
                media_type="application/json",
                sha256=content_sha256("synthetic canonical outer member"),
            ),
            result=comparison_result(selection.comparison),
            failure_code=None,
        )

    def read_comparison(
        self,
        query: InferenceTransferWorkflowReadRequest,
        *,
        selection: InferenceTransferPairSubmitRequest,
    ) -> InferenceTransferWorkflowReadResult:
        self.calls.append((query, selection))
        if self.on_read is not None:
            self.on_read(len(self.calls))
        if self.failure is not None:
            raise self.failure
        return self.value


class ArtifactPort:
    def __init__(self) -> None:
        self.payloads: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[ArtifactMemberPointer, int]] = []
        self.failure: Exception | None = None

    def read(self, pointer: ArtifactMemberPointer, *, maximum_bytes: int) -> bytes:
        self.calls.append((pointer, maximum_bytes))
        if self.failure is not None:
            raise self.failure
        return self.payloads[(pointer.artifact_id, pointer.artifact_revision_id)]


class PublisherPort:
    """Exercise exact-key semantics in memory, not the PostgreSQL/NAS publisher."""

    def __init__(self, artifacts: ArtifactPort) -> None:
        self.artifacts = artifacts
        self.calls: list[dict[str, Any]] = []
        self.history: dict[str, tuple[dict[str, Any], PublishedControlArtifact]] = {}
        self.on_publish: Callable[[], None] | None = None
        self.failure_after_commit: Exception | None = None

    def publish_bytes(self, **values: Any) -> PublishedControlArtifact:
        self.calls.append(values)
        # Preserve the actual existing publisher's control Artifact boundary;
        # an unconstrained fake would hide an unusable artifact_type.
        if not values["artifact_type"].startswith("control_"):
            raise ControlPlaneError("CONTROL_ARTIFACT_INVALID", "synthetic control type rejected")
        key = values["idempotency_key"]
        semantic = {name: value for name, value in values.items() if name != "created_at"}
        if key in self.history:
            previous, published = self.history[key]
            if previous != semantic:
                raise ControlPlaneError("CONTROL_ARTIFACT_CONFLICT", "synthetic conflicting replay")
        else:
            index = len(self.history) + 1
            token = f"{index:032x}"
            published = PublishedControlArtifact(
                job_id="job_" + token,
                pointer=ControlArtifactPointer(
                    artifact_id="artifact_" + token,
                    artifact_revision_id="rev_" + token,
                    sha256="sha256:" + hashlib.sha256(values["payload"]).hexdigest(),
                    schema_ref=values["schema_ref"],
                    media_type=values["media_type"],
                    logical_name=values["logical_name"],
                ),
                manifest_sha256=content_sha256("synthetic manifest " + token),
            )
            self.history[key] = (semantic, published)
            self.artifacts.payloads[
                (published.pointer.artifact_id, published.pointer.artifact_revision_id)
            ] = values["payload"]
        if self.on_publish is not None:
            self.on_publish()
        if self.failure_after_commit is not None:
            raise self.failure_after_commit
        return published


def member(published: PublishedControlArtifact) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id=published.pointer.artifact_id,
        artifact_revision_id=published.pointer.artifact_revision_id,
        member_path=published.pointer.logical_name,
        sha256=published.pointer.sha256,
        schema_ref=published.pointer.schema_ref,
        media_type=published.pointer.media_type,
    )


class Harness:
    def __init__(self, *, width: int = 1, reverse: bool = False) -> None:
        self.principal = PrincipalPort()
        self.snapshots = SnapshotPort(width=width)
        left, right = self.snapshots.records[:2]
        if reverse:
            left, right = right, left
        assert left.staged_entry is not None and right.staged_entry is not None
        comparison = comparison_request(left.staged_entry.profile, right.staged_entry.profile)
        self.selection = hashed(
            InferenceTransferPairSubmitRequest,
            "submission_sha256",
            comparison=comparison,
            snapshot_prepare=self.snapshots.prepare,
            expected_header_sha256=self.snapshots.prepared.header.header_sha256,
        )
        self.command = hashed(
            InferenceTransferHumanBundleCommand,
            "command_sha256",
            bundle_id="transferreviewbundle_" + "e" * 32,
            bundle_revision_id="transferreviewbundlerev_" + "f" * 32,
            created_at=(NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            selection=self.selection,
            workflow_id=WORKFLOW,
        )
        self.comparisons = ComparisonPort(self.selection)
        self.artifacts = ArtifactPort()
        self.publisher = PublisherPort(self.artifacts)
        self.clock = NOW
        self.owner = AuthenticatedInferenceTransferHumanReviewOwner(
            self.principal,
            self.snapshots,
            self.comparisons,
            self.artifacts,
            self.publisher,
            now=lambda: self.clock,
        )

    def evaluation(self, **changes: Any) -> HumanTransferEvaluation:
        comparison = self.selection.comparison
        return hashed(
            HumanTransferEvaluation,
            "evaluation_sha256",
            **(
                {
                    "evaluation_id": "transferevaluation_" + "3" * 32,
                    "evaluation_revision_id": "transferevaluationrev_" + "4" * 32,
                    "left_profile": comparison.left_profile,
                    "right_profile": comparison.right_profile,
                    "direction": "A_TO_B",
                    "rubric": comparison.rubric,
                    "reviewer_id": ACTOR,
                    "label": "CRUX_TRANSFERS",
                    "where_helped": ("두 조건을 연결하는 지점에서 도움이 됨",),
                    "reason": "실제 사용자 판단이 아닌 합성 테스트 label",
                    "evaluated_at": (NOW - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                }
                | changes
            ),
        )

    def record_command(
        self, pointer: ArtifactMemberPointer, *, evaluation: HumanTransferEvaluation | None = None
    ) -> InferenceTransferHumanRecordCommand:
        return hashed(
            InferenceTransferHumanRecordCommand,
            "command_sha256",
            bundle=pointer,
            evaluation=self.evaluation() if evaluation is None else evaluation,
        )


def human_bundle_command(*, reverse: bool = False) -> InferenceTransferHumanBundleCommand:
    return Harness(reverse=reverse).command


def human_bundle(*, reverse: bool = False) -> InferenceTransferHumanReviewBundle:
    harness = Harness(reverse=reverse)
    records = harness.snapshots.records[:2]
    return hashed(
        InferenceTransferHumanReviewBundle,
        "bundle_sha256",
        command=harness.command,
        prepared_by=ACTOR,
        comparison=harness.comparisons.value,
        sources=tuple(reversed(records)) if reverse else records,
    )


def human_record_command() -> InferenceTransferHumanRecordCommand:
    harness = Harness()
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "5" * 32,
        artifact_revision_id="rev_" + "6" * 32,
        member_path="result.json",
        schema_ref="eom://schemas/knowledge/item-inference-transfer-human-review-bundle/1.0",
        media_type="application/json",
        sha256=content_sha256(human_bundle().model_dump(mode="json")),
    )
    return harness.record_command(pointer)


def human_record() -> InferenceTransferHumanReviewRecord:
    command = human_record_command()
    return hashed(
        InferenceTransferHumanReviewRecord,
        "record_sha256",
        bundle=command.bundle,
        evaluation=command.evaluation,
    )
