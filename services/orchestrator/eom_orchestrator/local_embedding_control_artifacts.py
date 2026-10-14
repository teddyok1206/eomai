"""Publish native plan/policy values through the existing Orchestrator file-set owner."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eom_catalog_contracts.inference_transfer_embedding import (
    INPUT_SCHEMA_REF,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
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
from eom_workflow.reference_query_execution import (
    REFERENCE_QUERY_POLICY_REF,
    ReferenceQueryExecutionPolicy,
    parse_reference_query_execution_policy,
)
from pydantic import TypeAdapter

from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
    ControlFileSetPublisher,
    ControlPublicationTime,
)

SOURCE_PLAN_ARTIFACT_TYPE = "control_local_embedding_source_plan"
EXECUTION_POLICY_ARTIFACT_TYPE = "control_local_embedding_execution_policy"
REFERENCE_QUERY_POLICY_ARTIFACT_TYPE = "control_reference_query_execution_policy"
OWNED_INPUT_ARTIFACT_TYPE = "control_local_embedding_owned_input"


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
