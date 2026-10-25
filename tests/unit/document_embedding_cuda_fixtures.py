"""Real source/control Artifact IO; explicit synthetic IAM, Workflow row, root and model."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from eom_catalog_contracts.embedding_work_batch_result import build_embedding_work_batch_result
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionResources,
    execute_embedding_work_batch,
)
from eom_identifiers import sha256_bytes
from eom_workflow.embedding_batch_plan import EmbeddingBatchRoute, EmbeddingBatchSelection
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow_runner.document_embedding_cuda_execution import (
    CatalogCudaDocumentEmbeddingExecution,
)
from eom_workflow_runner.document_embedding_execution import OwnedDocumentEmbedding
from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    PublishedEmbeddingBatchExecution,
)
from eom_workflow_runner.local_embedding_encoding_admission import (
    CatalogEncodingOwnerAdmission,
    CurrentEncodingExecution,
)
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.reference_query_batch_execution_fixtures import query_plan_case
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_embedding_device_routing import policy_document
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_work_batch import Fence


def document_cuda_case(tmp_path, monkeypatch):
    fixture = native_fixture(device="CUDA")
    _query, template = query_plan_case(key="a" * 32)
    policy_body = policy_document("INDEX")
    for device in ("cpu", "cuda"):
        policy_body[device]["profile"] = getattr(template.policy, device).profile.model_dump(
            mode="json"
        )
    template.policy = EmbeddingDeviceRoutingPolicy.model_validate(
        seal(policy_body, "policy_sha256")
    )
    scope = seal(
        template.selection.scope.model_dump(mode="json")
        | dict(
            actor_id=fixture.request.actor_context.operator_id,
            storage_partition=fixture.request.namespace.storage_partition,
            access_policy_sha256=fixture.request.access_policy_sha256,
        ),
        "scope_sha256",
    )
    from tests.unit.test_embedding_batch_plan import planning_case

    original = planning_case(purpose="INDEX")
    body = original.selection.model_dump(mode="json") | dict(
        scope=scope,
        graph_snapshot=fixture.request.graph_snapshot.model_dump(mode="json"),
        access_policy_revision_id=fixture.request.access_policy_revision_id,
        views=[fixture.request.namespace.view],
    )
    template.selection = EmbeddingBatchSelection.model_validate(seal(body, "selection_sha256"))
    template.request = original.request
    value = source_case(tmp_path, monkeypatch, purpose="INDEX", planned=template)
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            original.route.observation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                policy_sha256=template.policy.policy_sha256,
            ),
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(template.policy, observation)
    route = EmbeddingBatchRoute.model_validate(
        seal(
            original.route.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                observation=observation.model_dump(mode="json"),
                decision=decision.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    registry = replace(
        value.catalog.configuration,
        namespace=fixture.request.namespace,
        space=fixture.request.space,
    )
    owner = object.__new__(CatalogLocalEmbeddingOwnerAdmission)
    owner.configuration = LocalEmbeddingOwnerConfiguration(
        registry,
        fixture.request.native_execution_policy,
        fixture.request.native_execution_policy_sha256,
    )
    owner.settings = value.catalog.settings
    owner.catalog = CatalogEmbeddingRegistryVerifier(
        value.engine, registry, identity_fence=Mock(), settings=owner.settings
    )
    owner.fence_current_actor = Mock()
    channel = SimpleNamespace(require_direct_peer=Mock())
    operation = SimpleNamespace(
        publisher=value.publisher, admission=value.owner, source_commit="a" * 40
    )
    active = ActiveEmbeddingBatchExecution(
        operation, value.request, SimpleNamespace(route=route), channel, object()
    )
    adapter = CatalogCudaDocumentEmbeddingExecution(active, owner, fixture.request)
    intent = fixture.association.intent
    execution = CurrentEncodingExecution(
        fixture.request,
        intent,
        CommandLeaseIdentity(intent.command_id, intent.runner_id, "lease", 1),
    )
    source = CatalogEncodingOwnerAdmission(owner, execution, adapter)
    source.resolve_launch = Mock(
        return_value=SimpleNamespace(
            owned_input=fixture.native_input,
            scope=SimpleNamespace(plan=fixture.plan, workflow_request=fixture.request),
        )
    )
    workflow = SimpleNamespace(
        idempotency_key=adapter.workflow_key,
        initial_request=fixture.request.model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=fixture.request.actor_context.operator_id,
    )
    get = Session.get

    def selected_get(session, entity, ident, **kwargs):
        if entity is WorkflowInstanceRecord:
            assert ident == intent.workflow_id
            return workflow
        return get(session, entity, ident, **kwargs)

    monkeypatch.setattr(Session, "get", selected_get)
    from eom_workflow_runner import embedding_batch_source_authorization as authorization_module

    monkeypatch.setattr(authorization_module, "require_command_lease", Mock())
    value.roots, value.runs = [], []

    @contextmanager
    def transaction():
        value.roots.append("open")
        with value.publisher.sessions.begin() as session:
            yield session
        value.roots.append("close")

    def run(_self, binding, batch, *, authorization):
        assert value.roots[-1] == "close"  # Caller is not holding SQL through compute.
        value.runs.append((binding, batch))
        authorization.authorize_batch()
        backend = SyntheticNativeBackend(fixture.native_input.space)
        backend.batch_size = backend.threads = 4

        @contextmanager
        def backend_scope():
            yield backend

        encoded = execute_embedding_work_batch(
            batch,
            resources=EmbeddingWorkBatchExecutionResources(
                batch.resource_profile_sha256, batch.timeout_seconds, batch.vector_max_bytes
            ),
            backend_scope=backend_scope,
            fence=Fence(),
        )
        vectors = b"".join(child.vectors for child in encoded.children)
        result = build_embedding_work_batch_result(
            batch, tuple(child.result for child in encoded.children), sha256_bytes(vectors)
        )
        verified = SimpleNamespace(
            assert_current=Mock(),
            staged=SimpleNamespace(batch=batch),
            result=result,
            child_vectors=(memoryview(vectors),),
        )
        return PublishedEmbeddingBatchExecution(SimpleNamespace(), verified)

    monkeypatch.setattr(ActiveEmbeddingBatchExecution, "run", run)
    value.adapter, value.owner, value.fixture = adapter, owner, fixture
    value.work = OwnedDocumentEmbedding(fixture.association, fixture.native_input)
    value.source, value.transaction, value.workflow = source, transaction, workflow
    return value
