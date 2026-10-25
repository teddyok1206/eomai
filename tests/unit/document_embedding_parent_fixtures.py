"""Canonical control IO with explicit synthetic service/Graph source leaves."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.local_indexing_mixed_policy import (
    supported_local_indexing_authorization_audit_sha256,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingSources,
)

from tests.unit.local_embedding_service_fixtures import service_fixture


@pytest.fixture
def parent_case(routed, monkeypatch):
    sources = routed.build()
    pair = sources.namespaces[0]
    base = service_fixture()
    grant = routed.grants[routed.selected.cuda_grants[0].service_policy_revision_id]
    gpu = pair.cuda.runtime_profile
    query = EmbeddingRegistryLookup(
        pair.cuda.owner.configuration.registry.corpus_id,
        pair.namespace,
        base.request.graph_snapshot,
        grant.source_access_policy_revision_id,
        grant.source_access_policy_sha256,
    )
    captured = ResolvedEmbeddingLookup(
        query.corpus_id,
        gpu.space,
        base.base.plan.recipe,
        base.base.plan.sources,
        base.base.entries,
    )
    targets = tuple(s.item_revision_id for s in captured.sources)
    plan = build_local_embedding_source_plan(query, captured, target_revision_ids=targets)
    saved = pair.cuda.controls.publish_observed_source_plan(
        plan, idempotency_key="test:parent-original-gpu-source-plan:" + uuid4().hex
    )
    with routed.publisher.sessions.begin() as session:
        controls = pair.cuda.owner.resolve_reconciliation_controls(session, query, gpu)
    body = base.request.model_dump(mode="json") | dict(
        corpus_id=query.corpus_id,
        graph_snapshot=query.graph_snapshot.model_dump(mode="json"),
        namespace=query.namespace.model_dump(mode="json"),
        access_policy_revision_id=query.policy_revision_id,
        access_policy_sha256=query.policy_sha256,
        space=gpu.space.model_dump(mode="json"),
        runtime_bundle=gpu.runtime_bundle.model_dump(mode="json"),
        resource_profile=gpu.resource_profile.model_dump(mode="json"),
        source_plan=saved.member.model_dump(mode="json"),
        source_plan_sha256=plan.plan_sha256,
        native_execution_policy=pair.cuda.owner.configuration.native_execution_policy.model_dump(
            mode="json"
        ),
        native_execution_policy_sha256=controls.policy.policy_sha256,
        actor_context=dict(
            kind="LOCAL_INDEXING_SERVICE",
            **controls.caller.service.model_dump(mode="json"),
            service_policy_revision_id=grant.access_policy_revision_id,
            service_policy_sha256=grant.content_sha256,
            authorization_audit_sha256=supported_local_indexing_authorization_audit_sha256(grant),
        ),
    )
    body.pop("request_sha256")
    request = parse_supported_local_embedding_request(
        body | {"request_sha256": content_sha256(body)}
    )
    original = ResolvedLocalEmbeddingSources(
        ResolvedLocalEmbeddingAdmission(request, plan, controls.policy), captured.entries
    )

    def resolve(owner, session, supplied):
        assert owner is pair.cuda.owner and supplied == request
        owner.fence_current_actor(session, supplied)
        return original

    def selected(session, caller, value):
        pair.cpu.owner.catalog.authorize_scope(session, caller, value.scope)
        assert value.source_revision_ids == tuple(sorted(targets))
        return ResolvedEmbeddingLookup(
            captured.corpus_id,
            pair.cpu.runtime_profile.space,
            captured.recipe,
            captured.sources,
            captured.entries,
        )

    monkeypatch.setattr(CatalogLocalEmbeddingOwnerAdmission, "resolve_sources", resolve)
    monkeypatch.setattr(pair.cpu.owner.catalog, "resolve_selected_sources", selected)
    return SimpleNamespace(
        routed=routed,
        sources=sources,
        pair=pair,
        request=request,
        plan=plan,
    )
