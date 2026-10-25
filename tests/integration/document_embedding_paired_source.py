"""Actual Catalog/Workflow persistence with an explicitly synthetic paired source/IAM seam."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutionPolicy
from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
from eom_workflow_runner.local_embedding_actor_authority import OperatorLocalEmbeddingActorAuthority
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_execution_context import native_embedding_registry_scope
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
    ResolvedLocalEmbeddingSources,
)
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingServicePreparation,
)
from eom_workflow_runner.local_indexing_routed_sources import PairedIndexingNamespacePreparation
from eom_workflow_runner.native_command_fence import NativeCommandMutationFence

from tests.unit.inference_transfer_embedding_fixtures import seal


def paired_gpu_source(
    cpu_owner, cpu_request, cpu_plan, cpu_profile, gpu_profile, publisher, monkeypatch
):
    """No live grant: only actual paired DB/commit behavior is evidence from this fixture."""
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    registry = cpu_owner.configuration.registry
    namespace = type(registry.namespace).model_validate(
        registry.namespace.model_dump(mode="json")
        | {"space_sha256": gpu_profile.space.space_sha256}
    )
    with publisher.sessions.begin() as session:
        original = cpu_owner.resolve_sources(session, cpu_request)
    policy = LocalEmbeddingExecutionPolicy.model_validate(
        seal(
            original.admission.policy.model_dump(mode="json")
            | dict(profiles=[gpu_profile.model_dump(mode="json")], default_device="CUDA"),
            "policy_sha256",
        )
    )
    saved_policy = controls.publish_policy(
        policy,
        idempotency_key="test:paired-gpu-policy:" + uuid4().hex,
        created_at=policy.created_at,
    )
    query = EmbeddingRegistryLookup(
        cpu_request.corpus_id,
        namespace,
        cpu_request.graph_snapshot,
        cpu_request.access_policy_revision_id,
        cpu_request.access_policy_sha256,
    )
    captured = ResolvedEmbeddingLookup(
        registry.corpus_id,
        gpu_profile.space,
        cpu_plan.recipe,
        cpu_plan.sources,
        original.entries,
    )
    plan = build_local_embedding_source_plan(
        query,
        captured,
        target_revision_ids=tuple(s.item_revision_id for s in cpu_plan.sources),
    )
    saved_plan = controls.publish_observed_source_plan(
        plan, idempotency_key="test:paired-gpu-plan:" + uuid4().hex
    )
    request = parse_supported_local_embedding_request(
        seal(
            cpu_request.model_dump(mode="json")
            | dict(
                namespace=namespace.model_dump(mode="json"),
                space=gpu_profile.space.model_dump(mode="json"),
                runtime_bundle=gpu_profile.runtime_bundle.model_dump(mode="json"),
                resource_profile=gpu_profile.resource_profile.model_dump(mode="json"),
                source_plan=saved_plan.member.model_dump(mode="json"),
                source_plan_sha256=plan.plan_sha256,
                native_execution_policy=saved_policy.member.model_dump(mode="json"),
                native_execution_policy_sha256=policy.policy_sha256,
            ),
            "request_sha256",
        )
    )
    owner = object.__new__(CatalogLocalEmbeddingOwnerAdmission)
    owner.configuration = LocalEmbeddingOwnerConfiguration(
        replace(registry, namespace=namespace, space=gpu_profile.space),
        saved_policy.member,
        policy.policy_sha256,
    )
    owner.settings = cpu_owner.settings
    owner._actor_authority = OperatorLocalEmbeddingActorAuthority(cpu_owner.identity)
    owner._command_fence = NativeCommandMutationFence()
    owner.catalog = CatalogEmbeddingRegistryVerifier(
        publisher.engine,
        owner.configuration.registry,
        identity_fence=cpu_owner.identity,
        settings=owner.settings,
    )

    def captured_source(session, caller, _query, phase):
        return cpu_owner.catalog._capture(
            session, caller, native_embedding_registry_scope(cpu_request), phase
        )

    monkeypatch.setattr(owner.catalog, "_capture", captured_source)
    monkeypatch.setattr(
        owner.catalog,
        "_capture_source",
        lambda session, caller, intent, *, artifact_reader, phase, source_revision_ids=(): (
            captured_source(session, caller, intent, phase)[1]
        ),
    )

    def resolve(session, supplied):
        assert supplied == request
        cpu_owner.resolve_sources(
            session, cpu_request
        )  # Late synthetic revocation remains effective.
        owner.fence_current_actor(session, supplied)
        return ResolvedLocalEmbeddingSources(
            ResolvedLocalEmbeddingAdmission(request, plan, policy), original.entries
        )

    monkeypatch.setattr(owner, "resolve_sources", resolve)
    monkeypatch.setattr(
        owner, "resolve_submission", lambda session, supplied: resolve(session, supplied).admission
    )

    def claim(session, *, command, workflow, request):
        assert command.workflow_id == workflow.workflow_id
        return resolve(session, request).admission

    monkeypatch.setattr(owner, "resolve_claim", claim)
    pair = PairedIndexingNamespacePreparation(
        LocalEmbeddingServicePreparation(cpu_owner, publisher, cpu_profile, source_commit="a" * 40),
        LocalEmbeddingServicePreparation(owner, publisher, gpu_profile, source_commit="a" * 40),
    )
    return SimpleNamespace(pair=pair, request=request, plan=plan)
