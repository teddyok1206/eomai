"""Existing source owners, local Artifact IO and synthetic IAM/command ports; no live grant."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_work_batch import parse_embedding_work_batch_input
from eom_identifiers import content_sha256
from eom_workflow.reference_query_execution import parse_reference_query_launch_association
from eom_workflow_runner import embedding_batch_source_authorization as module
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_encoding_admission import CurrentEncodingExecution
from eom_workflow_runner.local_embedding_owner_admission import ResolvedLocalEmbeddingSources
from eom_workflow_runner.reference_query_owner_admission import build_reference_query_native_input
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_local_embedding_encoding_admission import current as current
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_owner_admission import source as source


def batch_for(native, *, purpose, actor, partition, policy, resources):
    scope = seal(
        {
            "actor_kind": "OPERATOR",
            "actor_id": actor,
            "storage_partition": partition,
            "access_policy_sha256": policy,
        },
        "scope_sha256",
    )
    return parse_embedding_work_batch_input(
        seal(
            {
                "schema_version": "embedding-work-batch-input/1.0",
                "purpose": purpose,
                "scope": scope,
                "routing_decision_sha256": "sha256:" + "d" * 64,
                "resource_profile_sha256": resources.resource_profile_sha256,
                "timeout_seconds": 180,
                "vector_max_bytes": 16 * 1024**2,
                "children": [
                    {
                        "scope_sha256": scope["scope_sha256"],
                        "request": native.model_dump(mode="json"),
                    }
                ],
            },
            "request_sha256",
        )
    )


@pytest.fixture
def document(current, monkeypatch):
    fixture, port, session, owner, _launcher, _launch, _lease, artifacts = current
    intent = fixture.association.intent
    roots, late_leases = [], []

    @contextmanager
    def transaction():
        session.scalar.side_effect = (
            SimpleNamespace(
                workflow_id=intent.workflow_id, state="RUNNING", current_step_key="encode_batch"
            ),
            SimpleNamespace(
                workflow_id=intent.workflow_id,
                step_key="encode_batch",
                attempt=1,
                state="RUNNING",
                step_type="application",
                worker_role=None,
                result_schema="incremental-embedding-result@1.0",
                input_pointer_manifest={
                    "source_plan": fixture.request.source_plan.model_dump(mode="json"),
                    "source_plan_sha256": fixture.request.source_plan_sha256,
                },
            ),
        )
        roots.append("open")
        try:
            yield session
        finally:
            roots.append("close")

    monkeypatch.setattr(module, "require_command_lease", lambda *args: late_leases.append(args))
    batch = batch_for(
        fixture.native_input,
        purpose="DOCUMENT",
        actor=fixture.request.actor_context.operator_id,
        partition=fixture.request.namespace.storage_partition,
        policy=fixture.request.access_policy_sha256,
        resources=fixture.request.resource_profile,
    )
    selected = module.DocumentBatchSource(port, fixture.association, transaction)
    fence = module.CatalogEmbeddingBatchSourceAuthorization(batch, (selected,))
    return SimpleNamespace(
        fixture=fixture,
        owner=owner,
        port=port,
        batch=batch,
        source=selected,
        fence=fence,
        roots=roots,
        leases=late_leases,
        artifacts=artifacts,
    )


@pytest.fixture
def query(source, monkeypatch):
    base = case()
    with source.publisher.sessions.begin() as session:
        sources = source.owner.resolve_sources(session, source.request)
    native = build_reference_query_native_input(
        sources,
        job_id=base.launch.native_launch_job_id,
        query_request_id=base.launch.query_request_id,
    )
    launch = parse_reference_query_launch_association(
        seal(
            base.launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": source.request.request_sha256,
                "context_request_sha256": source.request.context_request.request_sha256,
                "query_request_sha256": native.request_sha256,
                "query_input_set_sha256": native.input_set_sha256,
                "recipe_sha256": native.recipe.recipe_sha256,
                "runtime_bundle": source.request.runtime_bundle.model_dump(mode="json"),
            },
            "association_sha256",
        )
    )
    lease = CommandLeaseIdentity(launch.original_command_id, "query-source-fixture", "lease", 1)
    state = SimpleNamespace(roots=[], leases=[], original=launch, deny_lease=False)

    @contextmanager
    def transaction():
        state.roots.append("open")
        try:
            with source.publisher.sessions.begin() as session:
                yield session
        finally:
            state.roots.append("close")

    def resolve(session, request, current_lease, **kwargs):
        assert request == source.request and current_lease == lease
        assert kwargs == dict(workflow_id=launch.workflow_id, step_run_id=launch.step_run_id)
        return source.owner.resolve_sources(session, request)

    def late(session, current_lease):
        assert current_lease == lease
        state.leases.append(current_lease)
        if state.deny_lease:
            raise ValueError("current command expired during source validation")

    monkeypatch.setattr(source.owner, "resolve_execution_sources", resolve)
    monkeypatch.setattr(
        module, "read_native_reference_query_launch", lambda *args, **kwargs: state.original
    )
    monkeypatch.setattr(module, "require_command_lease", late)
    batch = batch_for(
        native,
        purpose="REFERENCE_QUERY",
        actor=source.request.operator_audit.operator_id,
        partition=native.rows[0].encoding.storage_partition,
        policy=source.request.context_request.policy_sha256,
        resources=source.request.resource_profile,
    )
    selected = module.ReferenceQueryBatchSource(
        source.owner, source.request, launch, lease, transaction
    )
    state.source, state.batch, state.binding = source, batch, selected
    state.fence = module.CatalogEmbeddingBatchSourceAuthorization(batch, (selected,))
    return state


def test_document_reuses_actual_original_encoding_owner_each_time_without_cached_authority(
    document,
):
    for _ in range(2):
        document.fence.authorize_batch()
    assert document.roots == ["open", "close"] * 2
    assert document.owner.resolve_mutation_sources.call_count == 2
    assert document.artifacts.return_value.resolve_input.call_count == 2
    assert len(document.leases) == 2
    document.owner.identity.fence_current_operator.side_effect = PermissionError("revoked")
    with pytest.raises(PermissionError):
        document.fence.authorize_batch()
    assert document.artifacts.return_value.resolve_input.call_count == 2


def test_changed_document_artifact_input_is_not_replaced_by_current_or_latest(document):
    document.artifacts.return_value.resolve_input.return_value = None
    with pytest.raises((ValueError, AttributeError)):
        document.fence.authorize_batch()
    assert document.roots == ["open", "close"] and not document.leases


def test_indexing_service_child_keeps_machine_authority_without_operator_impersonation(
    document, monkeypatch
):
    service = service_fixture(base=document.fixture)
    request = service.request
    intent_body = document.fixture.association.intent.model_dump(mode="json")
    intent_body["workflow_request_sha256"] = request.request_sha256
    intent = seal(intent_body, "intent_sha256")
    association = module.parse_supported_embedding_association(
        seal(
            document.fixture.association.model_dump(mode="json") | {"intent": intent},
            "association_sha256",
        )
    )
    document.port.execution = CurrentEncodingExecution(
        request, association.intent, document.port.execution.command_lease
    )
    current = ResolvedLocalEmbeddingSources(
        ResolvedLocalEmbeddingAdmission(request, document.fixture.plan, service.policy),
        document.fixture.entries,
    )
    document.owner.resolve_mutation_sources.return_value = current
    service_calls = []
    document.owner.fence_current_actor.side_effect = lambda session, selected: service_calls.append(
        selected.actor_context.service_id
    )
    scope = seal(
        document.batch.scope.model_dump(mode="json")
        | {
            "actor_kind": "LOCAL_INDEXING_SERVICE",
            "actor_id": request.actor_context.service_id,
        },
        "scope_sha256",
    )
    body = document.batch.model_dump(mode="json") | {"scope": scope}
    body["children"][0]["scope_sha256"] = scope["scope_sha256"]
    batch = parse_embedding_work_batch_input(seal(body, "request_sha256"))
    source = module.DocumentBatchSource(document.port, association, document.source.transaction)
    fence = module.CatalogEmbeddingBatchSourceAuthorization(batch, (source,))
    fence.authorize_batch()
    assert service_calls == [request.actor_context.service_id] * 2
    document.owner.identity.fence_current_operator.assert_not_called()


def test_query_uses_actual_source_controls_and_original_launch_without_live_or_cached_grant(query):
    query.source.calls.clear()
    for _ in range(2):
        query.fence.authorize_batch()
    assert query.roots == ["open", "close"] * 2 and len(query.leases) == 2
    assert sum(name == "prepare" for name, _ in query.source.calls) == 2
    assert sum(name == "identity" for name, _ in query.source.calls) >= 6


@pytest.mark.parametrize("fault", ["actor", "late_actor", "lease", "launch", "input"])
def test_query_revocation_stale_launch_or_changed_input_is_never_authority(query, fault):
    if fault == "actor":
        query.source.deny = True
    elif fault == "late_actor":
        query.source.deny_at_end = True
    elif fault == "lease":
        query.deny_lease = True
    elif fault == "launch":
        query.original = None
    else:
        query.source.prepared = replace(
            query.source.prepared,
            query_texts=tuple(
                (view, "changed source text") for view, _text in query.source.prepared.query_texts
            ),
        )
    with pytest.raises((ValueError, RuntimeError)):
        query.fence.authorize_batch()
    assert query.roots == ["open", "close"]


@pytest.mark.parametrize("fixture_name", ["document", "query"])
@pytest.mark.parametrize("field", ["actor_id", "access_policy_sha256", "resource_profile_sha256"])
def test_small_scope_labels_do_not_override_the_actual_source_owner(request, fixture_name, field):
    value = request.getfixturevalue(fixture_name)
    body = value.batch.model_dump(mode="json")
    if field == "resource_profile_sha256":
        body[field] = "sha256:" + "f" * 64
    else:
        body["scope"][field] = "operator_foreign" if field == "actor_id" else "sha256:" + "f" * 64
        body["scope"] = seal(body["scope"], "scope_sha256")
        for child in body["children"]:
            child["scope_sha256"] = body["scope"]["scope_sha256"]
    batch = parse_embedding_work_batch_input(seal(body, "request_sha256"))
    binding = value.source if fixture_name == "document" else value.binding
    fence = module.CatalogEmbeddingBatchSourceAuthorization(batch, (binding,))
    with pytest.raises(ValueError):
        fence.authorize_batch()


@pytest.mark.parametrize("fixture_name", ["document", "query"])
def test_hash_lookup_is_bound_to_original_batch_and_never_parses_full_batch_per_frame(
    request, fixture_name, monkeypatch
):
    value = request.getfixturevalue(fixture_name)
    monkeypatch.setattr(
        module,
        "parse_embedding_work_batch_input",
        lambda *args: (_ for _ in ()).throw(AssertionError("whole batch parse per frame")),
    )
    key = value.batch.children[0].request.request_sha256
    value.fence.authorize_child(value.batch.request_sha256, key)
    with pytest.raises(ValueError):
        value.fence.authorize_child(content_sha256({"foreign": "batch"}), key)
    with pytest.raises(ValueError):
        value.fence.authorize_child(
            value.batch.request_sha256, content_sha256({"foreign": "child"})
        )
    assert value.roots == ["open", "close"]


def test_missing_or_wrong_purpose_source_binding_is_rejected_before_io(document, query):
    for sources in ((), (query.binding,), [document.source], (object(),)):
        with pytest.raises(ValueError):
            module.CatalogEmbeddingBatchSourceAuthorization(document.batch, sources)
    assert not document.roots and not query.roots
