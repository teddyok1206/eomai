"""Current-authorized human review on the existing Orchestrator Artifact boundary.

Human labels are explicit inputs, never inferred from model verdicts. A stored
bundle or its hash pins content, not access. Only exact replay is supported;
publication uncertainty or post-commit revocation never causes another submit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from eom_api_contracts.auth import CurrentOperator
from eom_catalog_contracts.inference_transfer_human_review import (
    HUMAN_REVIEW_BUNDLE_SCHEMA_REF,
    HUMAN_REVIEW_RECORD_SCHEMA_REF,
    MAX_HUMAN_REVIEW_BYTES,
    InferenceTransferHumanBundleCommand,
    InferenceTransferHumanRecordCommand,
    InferenceTransferHumanReviewBundle,
    InferenceTransferHumanReviewRecord,
    parse_human_bundle,
    parse_human_bundle_command,
    parse_human_record,
    parse_human_record_command,
    validate_human_record_context,
)
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
    parse_workflow_read_result,
    validate_workflow_read_result_context,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    parse_snapshot_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result,
)
from eom_catalog_contracts.item_inference_transfer import (
    HumanTransferEvaluation,
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import PermissionKey, RoleKey
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow import ControlArtifactPointer

from eom_orchestrator.control_artifacts import PublishedControlArtifact
from eom_orchestrator.control_service import ControlPlaneError


class HumanReviewPrincipalPort(Protocol):
    def read(self) -> CurrentOperator: ...


class HumanReviewSnapshotPort(Protocol):
    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult: ...


class HumanReviewComparisonPort(Protocol):
    def read_comparison(
        self,
        query: InferenceTransferWorkflowReadRequest,
        *,
        selection: InferenceTransferPairSubmitRequest,
    ) -> InferenceTransferWorkflowReadResult: ...


class HumanReviewArtifactPort(Protocol):
    def read(self, pointer: ArtifactMemberPointer, *, maximum_bytes: int) -> bytes: ...


class HumanReviewPublisherPort(Protocol):
    def publish_bytes(
        self,
        *,
        payload: bytes,
        logical_name: str,
        schema_ref: str,
        media_type: str,
        artifact_type: str,
        idempotency_key: str,
        created_at: datetime,
        source_commit: str,
    ) -> PublishedControlArtifact: ...


def _hashed[T: FrozenModel](model: type[T], field: str, **values: object) -> T:
    body = model.model_construct(_fields_set=set(values), **values).model_dump(
        mode="json", exclude={field}
    )
    return model.model_validate(body | {field: content_sha256(body)})


def _error(suffix: str) -> ControlPlaneError:
    return ControlPlaneError(
        "INFERENCE_TRANSFER_HUMAN_" + suffix, "exact current-authorized human review required"
    )


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = child
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON constant")


class AuthenticatedInferenceTransferHumanReviewOwner:
    """Small application leaf; no worker, Item approval, queue, or new registry."""

    def __init__(
        self,
        principal: HumanReviewPrincipalPort,
        snapshots: HumanReviewSnapshotPort,
        comparisons: HumanReviewComparisonPort,
        artifacts: HumanReviewArtifactPort,
        publisher: HumanReviewPublisherPort,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.principal, self.snapshots, self.comparisons = principal, snapshots, comparisons
        self.artifacts, self.publisher, self._now = artifacts, publisher, now
        self._operator_id: str | None = None
        self._session_id: str | None = None

    def _clock(self) -> datetime:
        now = self._now()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise _error("CLOCK_INVALID")
        return now

    def _current(self) -> CurrentOperator:
        try:
            value = CurrentOperator.model_validate(self.principal.read().model_dump(mode="json"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise _error("AUTHORIZATION_REQUIRED") from exc
        now = self._clock()
        required = {
            PermissionKey.WORKFLOW_READ.value,
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        }
        if (
            value.username != "guiadmin"
            or re.fullmatch(r"operator_[0-9a-f]{32}", value.operator_id) is None
            or re.fullmatch(r"apisession_[0-9a-f]{32}", value.session_id) is None
            or RoleKey.ADMIN.value not in value.roles
            or not required.issubset(value.effective_permissions)
            or value.password_change_required
            or value.access_expires_at <= now
            or not now - timedelta(minutes=15) <= value.authenticated_at <= now
            or (self._operator_id is not None and self._operator_id != value.operator_id)
            or (self._session_id is not None and self._session_id != value.session_id)
        ):
            raise _error("AUTHORIZATION_REQUIRED")
        if self._operator_id is None:
            self._operator_id, self._session_id = value.operator_id, value.session_id
        return value

    def _comparison(
        self, command: InferenceTransferHumanBundleCommand
    ) -> InferenceTransferWorkflowReadResult:
        principal = self._current()
        selection = command.selection
        if (
            "PAST_EXAM" in selection.snapshot_prepare.source_classes
            and PermissionKey.CONTENT_INTAKE_READ.value not in principal.effective_permissions
        ):
            raise _error("AUTHORIZATION_REQUIRED")
        query = _hashed(
            InferenceTransferWorkflowReadRequest,
            "read_sha256",
            workflow_id=command.workflow_id,
            mode="CANONICAL_RESULT",
        )
        value = parse_workflow_read_result(
            self.comparisons.read_comparison(query, selection=selection).model_dump(mode="json")
        )
        validate_workflow_read_result_context(query, value)
        prepare = selection.snapshot_prepare
        if (
            value.comparison != selection.comparison
            or value.graph_snapshot != prepare.graph_snapshot
            or value.access_policy_revision_id != prepare.access_policy_revision_id
            or value.access_policy_sha256 != prepare.access_policy_sha256
        ):
            raise _error("SOURCE_CHANGED")
        self._current()
        return value

    def _sources(
        self, command: InferenceTransferHumanBundleCommand
    ) -> tuple[InferenceTransferSnapshotRecord, ...]:
        actor = self._current().operator_id
        selection = command.selection
        prepared = parse_snapshot_result(
            self.snapshots.execute(actor, selection.snapshot_prepare).model_dump(mode="json")
        )
        if not isinstance(prepared, InferenceTransferSnapshotPrepareResult):
            raise _error("SOURCE_CHANGED")
        validate_snapshot_prepare_result(selection.snapshot_prepare, prepared)
        if (
            prepared.header.actor_id != actor
            or prepared.header.header_sha256 != selection.expected_header_sha256
        ):
            raise _error("SOURCE_CHANGED")
        order = (selection.comparison.left_profile, selection.comparison.right_profile)
        selected = frozenset(order)
        rows = tuple(row for row in prepared.index if row.profile in selected)
        if len(rows) != 2:
            raise _error("SOURCE_CHANGED")
        records: dict[InferenceTransferProfilePointer, InferenceTransferSnapshotRecord] = {}
        width = min(2, prepared.header.prepare.chunk_budget.max_entries)
        for start in range(0, len(rows), width):
            self._current()
            query = _hashed(
                InferenceTransferSnapshotReadRequest,
                "read_sha256",
                header=prepared.header,
                selected_index_entries=rows[start : start + width],
            )
            read = parse_snapshot_result(
                self.snapshots.execute(actor, query).model_dump(mode="json")
            )
            if not isinstance(read, InferenceTransferSnapshotReadResult):
                raise _error("SOURCE_CHANGED")
            validate_snapshot_read_result(query, read, index=prepared.index)
            for record in read.records:
                pointer = record.index_entry.profile
                if pointer is None or pointer in records:
                    raise _error("SOURCE_CHANGED")
                records[pointer] = record
        if set(records) != selected:
            raise _error("SOURCE_CHANGED")
        self._current()
        return tuple(records[pointer] for pointer in order)

    def _authorize_bundle(self, bundle: InferenceTransferHumanReviewBundle) -> None:
        if self._current().operator_id != bundle.prepared_by:
            raise _error("AUTHORIZATION_REQUIRED")
        if bundle.command.created_at > self._clock():
            raise _error("INPUT_INVALID")
        if self._comparison(bundle.command) != bundle.comparison:
            raise _error("SOURCE_CHANGED")
        if self._sources(bundle.command) != bundle.sources:
            raise _error("SOURCE_CHANGED")
        self._current()

    def _load(self, pointer: ArtifactMemberPointer, schema: str) -> object:
        self._current()
        pointer = ArtifactMemberPointer.model_validate(pointer.model_dump(mode="json"))
        if (
            pointer.schema_ref != schema
            or pointer.member_path != "result.json"
            or pointer.media_type != "application/json"
        ):
            raise _error("ARTIFACT_INVALID")
        raw = self.artifacts.read(pointer, maximum_bytes=MAX_HUMAN_REVIEW_BYTES)
        if not 0 < len(raw) <= MAX_HUMAN_REVIEW_BYTES or sha256_bytes(raw) != pointer.sha256:
            raise _error("ARTIFACT_INVALID")
        return json.loads(raw, object_pairs_hook=_unique_json, parse_constant=_reject_constant)

    def _publish(
        self,
        document: InferenceTransferHumanReviewBundle | InferenceTransferHumanReviewRecord,
        *,
        schema: str,
        key: str,
        source_commit: str,
    ) -> PublishedControlArtifact:
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise _error("INPUT_INVALID")
        self._current()
        payload = canonical_json_bytes(document.model_dump(mode="json"))
        if not 0 < len(payload) <= MAX_HUMAN_REVIEW_BYTES:
            raise _error("INPUT_INVALID")
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name="result.json",
            schema_ref=schema,
            media_type="application/json",
            artifact_type="control_inference_transfer_human_review",
            idempotency_key=key,
            created_at=self._clock(),
            source_commit=source_commit,
        )
        pointer = ControlArtifactPointer.model_validate(published.pointer.model_dump(mode="json"))
        if (
            pointer.logical_name != "result.json"
            or pointer.schema_ref != schema
            or pointer.media_type != "application/json"
            or pointer.sha256 != sha256_bytes(payload)
            or re.fullmatch(r"job_[0-9a-f]{32}", published.job_id) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", published.manifest_sha256) is None
        ):
            raise _error("PUBLICATION_INVALID")
        return published

    def publish_bundle(
        self, command: InferenceTransferHumanBundleCommand, *, source_commit: str
    ) -> PublishedControlArtifact:
        command = parse_human_bundle_command(command.model_dump(mode="json"))
        principal = self._current()
        if command.created_at > self._clock():
            raise _error("INPUT_INVALID")
        bundle = parse_human_bundle(
            _hashed(
                InferenceTransferHumanReviewBundle,
                "bundle_sha256",
                command=command,
                prepared_by=principal.operator_id,
                comparison=self._comparison(command),
                sources=self._sources(command),
            ).model_dump(mode="json")
        )
        if self._comparison(command) != bundle.comparison:
            raise _error("SOURCE_CHANGED")
        key = "human-bundle:" + content_sha256(
            {
                "operator_id": principal.operator_id,
                "bundle_id": command.bundle_id,
                "bundle_revision_id": command.bundle_revision_id,
            }
        ).removeprefix("sha256:")
        published = self._publish(
            bundle, schema=HUMAN_REVIEW_BUNDLE_SCHEMA_REF, key=key, source_commit=source_commit
        )
        # A post-commit revoke withholds the receipt; the canonical Job/Artifact
        # stays intact and a later explicit same-key replay can resolve it.
        if self._comparison(command) != bundle.comparison:
            raise _error("SOURCE_CHANGED")
        self._current()
        return published

    def read_bundle(self, pointer: ArtifactMemberPointer) -> InferenceTransferHumanReviewBundle:
        bundle = parse_human_bundle(self._load(pointer, HUMAN_REVIEW_BUNDLE_SCHEMA_REF))
        self._authorize_bundle(bundle)
        return bundle

    def _evaluation(
        self, bundle: InferenceTransferHumanReviewBundle, evaluation: HumanTransferEvaluation
    ) -> None:
        try:
            validate_human_record_context(bundle, evaluation)
        except ValueError as exc:
            raise _error("EVALUATION_INVALID") from exc
        principal = self._current()
        if (
            evaluation.reviewer_id != principal.operator_id
            or bundle.prepared_by != principal.operator_id
            or evaluation.evaluated_at > self._clock()
        ):
            raise _error("EVALUATION_INVALID")

    def publish_evaluation(
        self, command: InferenceTransferHumanRecordCommand, *, source_commit: str
    ) -> PublishedControlArtifact:
        command = parse_human_record_command(command.model_dump(mode="json"))
        bundle = self.read_bundle(command.bundle)
        self._evaluation(bundle, command.evaluation)
        record = parse_human_record(
            _hashed(
                InferenceTransferHumanReviewRecord,
                "record_sha256",
                bundle=command.bundle,
                evaluation=command.evaluation,
            ).model_dump(mode="json")
        )
        key = "human-evaluation:" + content_sha256(
            {
                "operator_id": self._current().operator_id,
                "evaluation_id": command.evaluation.evaluation_id,
                "evaluation_revision_id": command.evaluation.evaluation_revision_id,
            }
        ).removeprefix("sha256:")
        if self._comparison(bundle.command) != bundle.comparison:
            raise _error("SOURCE_CHANGED")
        published = self._publish(
            record, schema=HUMAN_REVIEW_RECORD_SCHEMA_REF, key=key, source_commit=source_commit
        )
        if self._comparison(bundle.command) != bundle.comparison:
            raise _error("SOURCE_CHANGED")
        self._current()
        return published

    def read_evaluation(self, pointer: ArtifactMemberPointer) -> InferenceTransferHumanReviewRecord:
        record = parse_human_record(self._load(pointer, HUMAN_REVIEW_RECORD_SCHEMA_REF))
        bundle = self.read_bundle(record.bundle)
        self._evaluation(bundle, record.evaluation)
        self._current()
        return record
