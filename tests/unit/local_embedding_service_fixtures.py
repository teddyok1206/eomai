"""Synthetic service controls only; no installed identity, source grant or execution."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    local_indexing_authorization_audit_sha256,
)
from eom_operator_identity import LocalIndexingServiceReference
from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
    LocalEmbeddingServiceExecutionPolicy,
)
from eom_workflow.local_embedding_request import LocalEmbeddingServiceWorkflowRequest

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import (
    NativeAdmissionFixture,
    member,
    native_fixture,
)
from tests.unit.test_local_indexing_policy_contracts import policy_document


@dataclass(frozen=True)
class ServiceNativeFixture:
    base: NativeAdmissionFixture
    grant: LocalIndexingAccessPolicy
    policy: LocalEmbeddingServiceExecutionPolicy
    request: LocalEmbeddingServiceWorkflowRequest


def service_fixture(
    *,
    base: NativeAdmissionFixture | None = None,
    service: LocalIndexingServiceReference | None = None,
    workflow_definition_sha256: str | None = None,
    runtime_configuration_sha256: str = "sha256:" + "3" * 64,
) -> ServiceNativeFixture:
    original = native_fixture() if base is None else base
    initial_grant = policy_document()
    reference = (
        LocalIndexingServiceReference.model_validate(initial_grant["service"])
        if service is None
        else service
    )
    policy_body = original.policy.model_dump(mode="json") | {
        "schema_version": "local-embedding-execution-policy/1.1",
        "admission_mode": "LOCAL_INDEXING_SERVICE_ONLY",
        "service": reference.model_dump(mode="json"),
        "workflow_definition_sha256": workflow_definition_sha256
        or original.request.workflow_definition_sha256,
    }
    policy = LocalEmbeddingServiceExecutionPolicy.model_validate(seal(policy_body, "policy_sha256"))
    grant = LocalIndexingAccessPolicy.model_validate(
        policy_document(
            service=reference.model_dump(mode="json"),
            runtime_configuration_sha256=runtime_configuration_sha256,
            corpus_id=original.request.corpus_id,
            graph_id=original.request.graph_snapshot.graph_id,
            source_access_policy_revision_id=original.request.access_policy_revision_id,
            source_access_policy_sha256=original.request.access_policy_sha256,
            namespaces=[original.request.namespace.model_dump(mode="json")],
            space=original.request.space.model_dump(mode="json"),
            recipe=original.plan.recipe.model_dump(mode="json"),
            native_execution_policy_sha256=policy.policy_sha256,
            resource_profile_sha256=original.request.resource_profile.resource_profile_sha256,
        )
    )
    body = original.request.model_dump(mode="json") | {
        "schema_version": "local-embedding-workflow-request/1.2",
        "workflow_definition_sha256": policy.workflow_definition_sha256,
        "actor_context": {
            "kind": "LOCAL_INDEXING_SERVICE",
            **reference.model_dump(mode="json"),
            "service_policy_revision_id": grant.access_policy_revision_id,
            "service_policy_sha256": grant.content_sha256,
            "authorization_audit_sha256": local_indexing_authorization_audit_sha256(grant),
        },
        "native_execution_policy": member(
            "policy.json",
            LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
            policy.model_dump(mode="json"),
            "4",
        ).model_dump(mode="json"),
        "native_execution_policy_sha256": policy.policy_sha256,
    }
    request = LocalEmbeddingServiceWorkflowRequest.model_validate(seal(body, "request_sha256"))
    return ServiceNativeFixture(original, grant, policy, request)
