"""Publish native plan/policy values through the existing Orchestrator file-set owner."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_POLICY_ARTIFACT_TYPE,
    BenchmarkExecutionPolicy,
    benchmark_policy_schema_ref,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    INPUT_SCHEMA_REF,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from eom_workflow.embedding_batch_execution_receipt import (
    BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
    EmbeddingBatchExecutionReceipt,
)
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchSelection,
    embedding_batch_selection_schema_ref,
    parse_embedding_batch_selection,
)
from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    EmbeddingDeviceRoutingPolicy,
)
from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingExecutionPolicy,
    LocalEmbeddingServiceExecutionPolicy,
    parse_local_embedding_execution_policy,
    parse_local_embedding_service_execution_policy,
)
from eom_workflow.local_embedding_source_plan import (
    LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)
from eom_workflow.local_embedding_source_plan_v2 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow.local_embedding_source_plan_v3 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF,
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
)
from eom_workflow.private_chat_query_execution import (
    PRIVATE_CHAT_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicy,
)
from eom_workflow.reference_query_execution import (
    REFERENCE_QUERY_POLICY_REF,
    ReferenceQueryExecutionPolicy,
    parse_reference_query_execution_policy,
)
from eom_workflow.reference_query_routed_preparation import (
    PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF,
    ROUTED_QUERY_PREPARATION_SCHEMA_REF,
    PublicRoutedReferenceQueryPreparation,
    RoutedReferenceQueryPreparation,
    SupportedRoutedReferenceQueryPreparation,
    routed_reference_query_preparation_key,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
    ControlFileSetPublisher,
    ControlPublicationTime,
)
from eom_orchestrator.models import JobRecord

SOURCE_PLAN_ARTIFACT_TYPE = "control_local_embedding_source_plan"
EXECUTION_POLICY_ARTIFACT_TYPE = "control_local_embedding_execution_policy"
REFERENCE_QUERY_POLICY_ARTIFACT_TYPE = "control_reference_query_execution_policy"
REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE = "control_reference_query_routed_preparation"
PRIVATE_CHAT_QUERY_POLICY_ARTIFACT_TYPE = "control_private_chat_query_execution_policy"
OWNED_INPUT_ARTIFACT_TYPE = "control_local_embedding_owned_input"
BATCH_SELECTION_ARTIFACT_TYPE = "control_embedding_batch_selection"
DEVICE_ROUTING_POLICY_ARTIFACT_TYPE = "control_embedding_device_routing_policy"
BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE = "control_embedding_batch_execution_receipt"


def batch_execution_receipt_publication_key(
    parent_request_sha256: str, allocation_record_sha256: str
) -> str:
    """Identity of an original completion; no authority or implicit latest."""
    validator = TypeAdapter(Sha256)
    validator.validate_python(parent_request_sha256, strict=True)
    validator.validate_python(allocation_record_sha256, strict=True)
    return "embedding-batch-executed:" + content_sha256(
        dict(
            parent_request_sha256=parent_request_sha256,
            allocation_record_sha256=allocation_record_sha256,
        )
    ).removeprefix("sha256:")


def batch_execution_publication_exists(
    session: Session, *, parent_request_sha256: str, allocation_record_sha256: str
) -> bool:
    """Indexed original publication intent; incomplete/conflicting is not missing.

    Maintenance callers hold the original Workflow/launch fence in this same
    transaction. This metadata read neither resolves content nor grants a retry.
    """
    key = batch_execution_receipt_publication_key(parent_request_sha256, allocation_record_sha256)
    return (
        session.scalar(select(JobRecord.job_id).where(JobRecord.idempotency_key == key)) is not None
    )


@dataclass(frozen=True, slots=True)
class PublishedLocalEmbeddingControl:
    """Publication receipt, not a released execution policy or source permission."""

    owner_job_id: str
    member: ArtifactMemberPointer
    semantic_sha256: str
    manifest_sha256: str


class LocalEmbeddingControlArtifactPublisher:
    """No new publication protocol; authorization stays with the current owner operation."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        if type(source_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ValueError("LOCAL_EMBEDDING_CONTROL_SOURCE_INVALID")
        self.publisher = publisher
        self.source_commit = source_commit

    def publish_source_plan(
        self,
        plan: LocalEmbeddingSourcePlan,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        checked = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.plan_sha256,
            member="source-plan.json",
            schema=LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
            artifact_type=SOURCE_PLAN_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_batch_selection(
        self,
        selection: SupportedEmbeddingBatchSelection,
        *,
        idempotency_key: str,
    ) -> PublishedLocalEmbeddingControl:
        """Canonical bounded selection, not source permission or a compute grant."""
        checked = parse_embedding_batch_selection(selection)
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.selection_sha256,
            member="selection.json",
            schema=embedding_batch_selection_schema_ref(checked),
            artifact_type=BATCH_SELECTION_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def reuse_or_publish_batch_selection(
        self, selection: SupportedEmbeddingBatchSelection, *, idempotency_key: str
    ) -> ArtifactMemberPointer:
        """Preserve original equivalent bytes across a metadata-owner release change.

        The immutable original publisher/source remains recorded. This does not
        activate an older policy or substitute another selection's contents.
        """
        checked = parse_embedding_batch_selection(selection)
        saved = self.publisher.find_published(
            idempotency_key=idempotency_key, artifact_type=BATCH_SELECTION_ARTIFACT_TYPE
        )
        if saved is None:
            return self.publish_batch_selection(checked, idempotency_key=idempotency_key).member
        if saved.primary_file != "selection.json" or saved.primary_sha256 != sha256_bytes(
            canonical_json_bytes(checked)
        ):
            raise ValueError("BATCH_SELECTION_PUBLICATION_CONFLICT")
        return ArtifactMemberPointer(
            artifact_id=saved.artifact_id,
            artifact_revision_id=saved.artifact_revision_id,
            member_path="selection.json",
            sha256=saved.primary_sha256,
            schema_ref=embedding_batch_selection_schema_ref(checked),
            media_type="application/json",
        )

    def publish_batch_execution_receipt(
        self, receipt: EmbeddingBatchExecutionReceipt, *, idempotency_key: str
    ) -> PublishedLocalEmbeddingControl:
        """Current application authority is mandatory outside this publication leaf."""
        checked = EmbeddingBatchExecutionReceipt.model_validate(
            raw_similarity_contract_value(receipt)
        )
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.receipt_sha256,
            member="receipt.json",
            schema=BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
            artifact_type=BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def find_batch_execution_receipt(
        self, *, parent_request_sha256: str, allocation_record_sha256: str
    ) -> ArtifactMemberPointer | None:
        """Original canonical completion pointer; caller reauthorizes and resolves its bytes."""
        saved = self.publisher.find_published(
            idempotency_key=batch_execution_receipt_publication_key(
                parent_request_sha256, allocation_record_sha256
            ),
            artifact_type=BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,
        )
        if saved is None:
            return None
        if saved.primary_file != "receipt.json":
            raise ValueError("BATCH_EXECUTION_RECEIPT_PUBLICATION_INVALID")
        return ArtifactMemberPointer(
            artifact_id=saved.artifact_id,
            artifact_revision_id=saved.artifact_revision_id,
            member_path="receipt.json",
            sha256=saved.primary_sha256,
            schema_ref=BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
            media_type="application/json",
        )

    def publish_device_routing_policy(
        self,
        policy: EmbeddingDeviceRoutingPolicy,
        *,
        idempotency_key: str,
    ) -> PublishedLocalEmbeddingControl:
        """Publish a candidate without implicitly activating either runtime."""
        checked = EmbeddingDeviceRoutingPolicy.model_validate(raw_similarity_contract_value(policy))
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.policy_sha256,
            member="policy.json",
            schema=EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
            artifact_type=DEVICE_ROUTING_POLICY_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def publish_observed_source_plan(
        self,
        plan: LocalEmbeddingSourcePlan,
        *,
        idempotency_key: str,
    ) -> PublishedLocalEmbeddingControl:
        """Unattended plan replay uses its first actual publication timestamp."""
        checked = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.plan_sha256,
            member="source-plan.json",
            schema=LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
            artifact_type=SOURCE_PLAN_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def publish_source_plan_v2(
        self,
        plan: LocalEmbeddingSourcePlanV2,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        """Explicit mixed family over the same immutable file-set publication owner."""
        checked = parse_local_embedding_source_plan_v2(plan)
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.plan_sha256,
            member="source-plan.json",
            schema=LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
            artifact_type=SOURCE_PLAN_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_observed_source_plan_v2(
        self, plan: LocalEmbeddingSourcePlanV2, *, idempotency_key: str
    ) -> PublishedLocalEmbeddingControl:
        """Retain the first observed publication time for exact unattended plan2 replay."""
        checked = parse_local_embedding_source_plan_v2(plan)
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.plan_sha256,
            member="source-plan.json",
            schema=LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
            artifact_type=SOURCE_PLAN_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def publish_observed_source_plan_v3(
        self, plan: LocalEmbeddingSourcePlanV3, *, idempotency_key: str
    ) -> PublishedLocalEmbeddingControl:
        checked = parse_local_embedding_source_plan_v3(plan)
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.plan_sha256,
            member="source-plan.json",
            schema=LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF,
            artifact_type=SOURCE_PLAN_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def publish_policy(
        self,
        policy: LocalEmbeddingExecutionPolicy,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        checked = parse_local_embedding_execution_policy(policy.model_dump(mode="json"))
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.policy_sha256,
            member="policy.json",
            schema=LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
            artifact_type=EXECUTION_POLICY_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_service_policy(
        self,
        policy: LocalEmbeddingServiceExecutionPolicy,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        """Explicit successor; never reinterpret an operator policy or self-activate it."""
        checked = LocalEmbeddingServiceExecutionPolicy.model_validate(policy)
        checked = parse_local_embedding_service_execution_policy(checked.model_dump(mode="json"))
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.policy_sha256,
            member="policy.json",
            schema=LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
            artifact_type=EXECUTION_POLICY_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_owned_input(
        self,
        request: IncrementalEmbeddingInput,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        """Persist one admitted owned subset before binding its launch association.

        The encoding owner already holds current source/command authorization and
        reservations. This leaf validates bytes only; publication is not admission.
        Original all-demand Workflow request and source plan remain unchanged.
        """
        checked = parse_incremental_embedding_input(request.model_dump(mode="json"))
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.request_sha256,
            member="input.json",
            schema=INPUT_SCHEMA_REF,
            artifact_type=OWNED_INPUT_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_reference_query_policy(
        self,
        policy: ReferenceQueryExecutionPolicy,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        """QUERY controls stay distinct from DOCUMENT seed policy; no release or grant."""
        checked = parse_reference_query_execution_policy(policy)
        return self._publish(
            raw=canonical_json_bytes(checked.model_dump(mode="json")),
            semantic_sha256=checked.policy_sha256,
            member="policy.json",
            schema=REFERENCE_QUERY_POLICY_REF,
            artifact_type=REFERENCE_QUERY_POLICY_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_routed_reference_query_preparation(
        self, preparation: RoutedReferenceQueryPreparation
    ) -> PublishedLocalEmbeddingControl:
        """Current actual owner authorizes before publication; this leaf never grants access."""
        checked = RoutedReferenceQueryPreparation.model_validate(preparation)
        return self._publish_routed_query_preparation(checked, ROUTED_QUERY_PREPARATION_SCHEMA_REF)

    def publish_public_routed_reference_query_preparation(
        self, preparation: PublicRoutedReferenceQueryPreparation
    ) -> PublishedLocalEmbeddingControl:
        checked = PublicRoutedReferenceQueryPreparation.model_validate(preparation)
        return self._publish_routed_query_preparation(
            checked, PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF
        )

    def _publish_routed_query_preparation(
        self, checked: SupportedRoutedReferenceQueryPreparation, schema: str
    ) -> PublishedLocalEmbeddingControl:
        return self._publish(
            raw=canonical_json_bytes(checked),
            semantic_sha256=checked.preparation_sha256,
            member="preparation.json",
            schema=schema,
            artifact_type=REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE,
            idempotency_key=routed_reference_query_preparation_key(
                checked.operator_id, checked.idempotency_key
            ),
            created_at=ControlPublicationTime.FIRST_OBSERVATION,
        )

    def find_routed_reference_query_preparation(
        self, *, operator_id: str, idempotency_key: str
    ) -> ArtifactMemberPointer | None:
        """Exact original metadata pointer; the caller must still authorize and dereference it."""
        return self._find_routed_query_preparation(
            operator_id, idempotency_key, ROUTED_QUERY_PREPARATION_SCHEMA_REF
        )

    def find_public_routed_reference_query_preparation(
        self, *, operator_id: str, idempotency_key: str
    ) -> ArtifactMemberPointer | None:
        return self._find_routed_query_preparation(
            operator_id, idempotency_key, PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF
        )

    def _find_routed_query_preparation(
        self, operator_id: str, idempotency_key: str, schema: str
    ) -> ArtifactMemberPointer | None:
        saved = self.publisher.find_published(
            idempotency_key=routed_reference_query_preparation_key(operator_id, idempotency_key),
            artifact_type=REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE,
        )
        if saved is None:
            return None
        if saved.primary_file != "preparation.json":
            raise ValueError("REFERENCE_QUERY_ROUTED_PREPARATION_PUBLICATION_INVALID")
        return ArtifactMemberPointer(
            artifact_id=saved.artifact_id,
            artifact_revision_id=saved.artifact_revision_id,
            member_path="preparation.json",
            sha256=saved.primary_sha256,
            schema_ref=schema,
            media_type="application/json",
        )

    def publish_private_chat_query_policy(
        self,
        policy: PrivateChatQueryExecutionPolicy,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        """Private controls only; neither reference admission nor current Chat authority."""
        try:
            checked = PrivateChatQueryExecutionPolicy.model_validate(
                raw_similarity_contract_value(policy)
            )
        except (ValueError, TypeError, SchemaError):
            raise ValueError("PRIVATE_CHAT_QUERY_CONTROL_INVALID") from None
        return self._publish(
            raw=canonical_json_bytes(checked),
            semantic_sha256=checked.policy_sha256,
            member="policy.json",
            schema=PRIVATE_CHAT_QUERY_POLICY_REF,
            artifact_type=PRIVATE_CHAT_QUERY_POLICY_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def publish_benchmark_policy(
        self,
        policy: BenchmarkExecutionPolicy,
        *,
        idempotency_key: str,
        created_at: datetime,
    ) -> PublishedLocalEmbeddingControl:
        """A candidate Artifact, never administrator authentication or activation."""
        raw = embedding_device_benchmark_bytes(policy)
        return self._publish(
            raw=raw,
            semantic_sha256=policy.policy_sha256,
            member="policy.json",
            schema=benchmark_policy_schema_ref(policy),
            artifact_type=BENCHMARK_POLICY_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def _publish(
        self,
        *,
        raw: bytes,
        semantic_sha256: str,
        member: str,
        schema: str,
        artifact_type: str,
        idempotency_key: str,
        created_at: datetime | ControlPublicationTime,
    ) -> PublishedLocalEmbeddingControl:
        # An explicit local materialization boundary; only the existing owner
        # publishes to NAS. A plan body (up to 64 MiB) never becomes a DB value.
        if created_at is not ControlPublicationTime.FIRST_OBSERVATION:
            created_at = TypeAdapter(UtcDatetime).validate_python(created_at)
        digest = sha256_bytes(raw)
        with tempfile.TemporaryDirectory(
            prefix="native-controls-", dir=self.publisher.settings.workspace_root
        ) as directory:
            path = Path(directory) / member
            path.write_bytes(raw)
            path.chmod(0o600)
            members = (
                ControlFileSetMember(member, path, digest, len(raw), schema, "application/json"),
            )
            if created_at is ControlPublicationTime.FIRST_OBSERVATION:
                published = self.publisher.publish_first_observation(
                    members=members,
                    primary_file=member,
                    artifact_type=artifact_type,
                    manifest_version=CONTROL_FILE_SET_PROTOCOL,
                    idempotency_key=idempotency_key,
                    source_commit=self.source_commit,
                )
            else:
                published = self.publisher.publish(
                    members=members,
                    primary_file=member,
                    artifact_type=artifact_type,
                    manifest_version=CONTROL_FILE_SET_PROTOCOL,
                    idempotency_key=idempotency_key,
                    source_commit=self.source_commit,
                    created_at=created_at,
                )
        if published.primary_file != member or published.primary_sha256 != digest:
            # A commit may have happened. Preserve it and reconcile the same key.
            raise ValueError("LOCAL_EMBEDDING_CONTROL_RECEIPT_INVALID")
        return PublishedLocalEmbeddingControl(
            owner_job_id=TypeAdapter(JobId).validate_python(published.job_id),
            member=ArtifactMemberPointer(
                artifact_id=published.artifact_id,
                artifact_revision_id=published.artifact_revision_id,
                member_path=member,
                schema_ref=schema,
                media_type="application/json",
                sha256=digest,
            ),
            semantic_sha256=semantic_sha256,
            manifest_sha256=TypeAdapter(Sha256).validate_python(published.manifest_sha256),
        )
