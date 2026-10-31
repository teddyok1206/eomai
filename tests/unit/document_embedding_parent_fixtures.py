"""Canonical control IO with explicit synthetic service/Graph source leaves."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.local_indexing_mixed_policy import (
    supported_local_indexing_authorization_audit_sha256,
)
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_catalog_service.local_embedding_source_plan_v3 import (
    build_local_embedding_source_plan_v3,
    build_local_embedding_source_plan_v4,
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
from eom_workflow.local_embedding_source_plan_v4 import parse_local_embedding_source_plan_v4
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingSources,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_local_embedding_source_plan_v3 import inputs as public_inputs
from tests.unit.test_local_embedding_source_plan_v4 import entries as registered_entries
from tests.unit.test_local_embedding_source_plan_v4 import plan_value


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
        pair.maximum_sources,
    )
    public = isinstance(pair.namespace, PublicSolutionIndexNamespace)
    registered = routed.registered_public
    entries = base.base.entries
    registered_sources = base.base.plan.sources
    recipe = base.base.plan.recipe
    if public:
        entries = tuple(
            type(entry).model_validate(
                seal(
                    entry.model_dump(mode="json")
                    | {
                        "graph_snapshot": query.graph_snapshot.model_dump(mode="json"),
                        "policy_revision_id": query.policy_revision_id,
                        "policy_sha256": query.policy_sha256,
                    },
                    "entry_sha256",
                )
            )
            for entry in (
                registered_entries(parse_local_embedding_source_plan_v4(plan_value()))
                if registered
                else public_inputs()[1].entries
            )
        )
        registered_sources = tuple(entry.source for entry in entries)
        recipe = entries[0].recipe
    captured = ResolvedEmbeddingLookup(
        query.corpus_id,
        gpu.space,
        recipe,
        registered_sources,
        entries,
        base_analysis_run_ids=tuple(
            (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in entries
        )
        if public
        else (),
    )
    targets = tuple(s.item_revision_id for s in captured.sources)
    build_plan = (
        build_local_embedding_source_plan_v4
        if registered
        else build_local_embedding_source_plan_v3
        if public
        else build_local_embedding_source_plan
    )
    plan = build_plan(query, captured, target_revision_ids=targets)
    publish_plan = (
        pair.cuda.controls.publish_observed_source_plan_v4
        if registered
        else pair.cuda.controls.publish_observed_source_plan_v3
        if public
        else pair.cuda.controls.publish_observed_source_plan
    )
    saved = publish_plan(
        plan, idempotency_key="test:parent-original-gpu-source-plan:" + uuid4().hex
    )
    with routed.publisher.sessions.begin() as session:
        controls = pair.cuda.owner.resolve_reconciliation_controls(session, query, gpu)
    body = base.request.model_dump(mode="json") | dict(
        schema_version="local-embedding-workflow-request/4.0"
        if registered
        else "local-embedding-workflow-request/3.0"
        if public
        else base.request.schema_version,
        workflow_definition_version="2.0.0" if public else base.request.workflow_definition_version,
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
            base_analysis_run_ids=captured.base_analysis_run_ids,
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
