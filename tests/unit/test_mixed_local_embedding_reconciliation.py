"""Real temp control/queue persistence with synthetic current source/IAM, no model."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    parse_supported_embedding_binding,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_refresh_plan import mixed_index_membership_refresh_reason
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    MissingEmbeddingBindings,
    PreparedEmbeddingBindingLookup,
)
from eom_catalog_service.embedding_source_associations import embedding_binding_lookup_key
from eom_identifiers import content_sha256
from eom_orchestrator.models import Base, JobRecord
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_request_v2 import parse_local_embedding_workflow_request_v2
from eom_workflow_runner import local_embedding_service_reconciliation as application
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_service_reconciliation import ReconciliationState
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal, shard_pointer, vector_shard
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_mixed_local_embedding_owner_admission import mixed_owner as mixed_owner
from tests.unit.test_postgres_local_indexing_fence import case as case


def bindings_for(c):
    request, plan = c.scope.request, c.scope.plan
    shard = vector_shard(tuple(d.encoding for d in plan.demands), space=plan.space)
    pointer = shard_pointer(shard)
    sources = {s.item_revision_id: s for s in plan.sources}
    values = []
    for demand in plan.demands:
        registered = demand.evidence_kind == "REGISTERED_ITEM_REVIEW_SOLUTION"
        body = {
            "schema_version": "embedding-source-binding/2.0"
            if registered
            else "embedding-source-binding/1.0",
            "source": sources[demand.source_revision_id].model_dump(mode="json"),
            "profile": demand.profile.model_dump(mode="json"),
            "graph_snapshot": plan.graph_snapshot.model_dump(mode="json"),
            "policy_revision_id": request.access_policy_revision_id,
            "policy_sha256": request.access_policy_sha256,
            "recipe": plan.recipe.model_dump(mode="json"),
            "view": plan.namespace.view,
            "projection_version": "registered-item-review-comparison/1.0"
            if registered
            else "accepted-solution-comparison/1.0",
            "encoding": demand.encoding.model_dump(mode="json"),
            "row_ref": {
                "shard_manifest": pointer.model_dump(mode="json"),
                "row_index": shard.rows.index(demand.encoding),
                "encoding_sha256": demand.encoding.encoding_sha256,
            },
        }
        if registered:
            body.update(
                base_analysis_run_id=demand.base_analysis_run_id,
                review_evidence=demand.review_evidence.model_dump(mode="json"),
            )
        else:
            body["solution_evidence"] = demand.solution_evidence.model_dump(mode="json")
        values.append(parse_supported_embedding_binding(seal(body, "binding_sha256")))
    return tuple(sorted(values, key=lambda b: b.source.item_revision_id))


def index_for(bindings, plan):
    index = MixedEmbeddingIndexManifest.model_validate(
        seal(
            {
                "schema_version": "embedding-index-manifest/2.0",
                "index_id": "embeddingindex_" + "a" * 32,
                "index_revision_id": "embeddingindexrev_" + "a" * 32,
                "previous_manifest": None,
                "storage_partition": plan.namespace.storage_partition,
                "space": plan.space.model_dump(mode="json"),
                "view": plan.namespace.view,
                "recipe": plan.recipe.model_dump(mode="json"),
                "shards": [
                    p.model_dump(mode="json")
                    for p in sorted(
                        {b.row_ref.shard_manifest for b in bindings}, key=lambda p: p.artifact_id
                    )
                ],
                "bindings": [b.model_dump(mode="json") for b in bindings],
                "created_at": "2026-10-19T00:00:00Z",
            },
            "index_sha256",
        )
    )
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "b" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/2.0",
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )
    return pointer, index


@pytest.fixture
def reconciliation(mixed_owner, monkeypatch):
    c = mixed_owner
    Base.metadata.create_all(
        c.publisher.engine,
        tables=[
            m.__table__
            for m in (
                WorkflowDefinitionRecord,
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                WorkflowEventRecord,
            )
        ],
    )
    with c.publisher.sessions.begin() as session:
        import_workflow_definition(session, c.compiled)
    request = c.scope.request
    query = EmbeddingRegistryLookup(
        request.corpus_id,
        request.namespace,
        request.graph_snapshot,
        request.access_policy_revision_id,
        request.access_policy_sha256,
    )
    full = bindings_for(c)
    current = SimpleNamespace(missing=full, bindings=(), previous=None, reusable_rows=None)

    def current_lookup(gate, session, configuration):
        gate.authorize_scope(session, c.owner.registry_caller(request), query, configuration)
        return query

    def prepare(session, caller, actual_query, verifier):
        assert actual_query == query and verifier is c.owner.catalog
        verifier.authorize_scope(session, caller, query)
        return PreparedEmbeddingBindingLookup(
            MissingEmbeddingBindings(
                tuple(embedding_binding_lookup_key(b) for b in current.missing),
                tuple(RegisteredEmbeddingRow(b.encoding, b.row_ref) for b in current.bindings)
                if current.reusable_rows is None
                else current.reusable_rows,
                len(c.current.sources),
                len(c.current.entries),
            ),
            c.current,
            current.bindings,
        )

    def selected(session, caller, selection):
        c.owner.catalog.authorize_scope(session, caller, selection.scope)
        ids = set(selection.source_revision_ids)
        return replace(
            c.current,
            sources=tuple(s for s in c.current.sources if s.item_revision_id in ids),
            entries=tuple(
                e
                for e in c.current.entries
                if e.profile.source_basis.source.item_revision_id in ids
            ),
            base_analysis_run_ids=tuple(
                (k, v) for k, v in c.current.base_analysis_run_ids if k in ids
            ),
        )

    monkeypatch.setattr(CatalogIndexingRegistrySourceAuthority, "current_lookup", current_lookup)
    monkeypatch.setattr(application, "prepare_missing_embedding_bindings", prepare)
    monkeypatch.setattr(c.owner.catalog, "resolve_selected_sources", selected)
    monkeypatch.setattr(
        c.owner.catalog, "resolve_indexing_namespace_predecessor", lambda *_: current.previous
    )
    launcher = Mock(spec=FixedNativeIndexLauncher)
    executor = CatalogNativeEmbeddingExecutor(
        owner=c.owner,
        publisher=c.publisher,
        execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
        runtime_profile=c.scope.policy.profiles[0],
        source_commit="a" * 40,
    )
    return SimpleNamespace(
        source=c,
        current=current,
        full=full,
        query=query,
        launcher=launcher,
        app=application.LocalEmbeddingServiceReconciliation(executor, maximum_targets=1),
    )


def counts(c):
    with c.source.publisher.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(m))
            for m in (WorkflowInstanceRecord, WorkflowCommandRecord, JobRecord)
        )


def read_plan(c, result):
    with c.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, result.workflow_id)
        request = parse_local_embedding_workflow_request_v2(workflow.initial_request)
        assert workflow.definition_version == "2.0.0"
        return request, c.source.owner.resolve_submission(session, request).plan


def test_new_numeric_targets_remain_bounded_and_same_key_replays(reconciliation):
    c = reconciliation
    before = counts(c)
    first, again = c.app.run_once(), c.app.run_once()
    assert first.state is ReconciliationState.QUEUED and again.state is ReconciliationState.REPLAYED
    assert first.workflow_id == again.workflow_id and first.command_id == again.command_id
    assert first.missing_binding_count == 2 and first.selected_target_count == 1
    request, plan = read_plan(c, first)
    assert request.schema_version == "local-embedding-workflow-request/2.0"
    assert len(plan.sources) == len(plan.demands) == 1
    assert counts(c) == (1, 1, before[2] + 1)
    c.launcher.run.assert_not_called()


@pytest.mark.parametrize(
    ("cached_indexes", "maximum_targets", "expected_indexes"),
    (
        pytest.param((0,), 1, (1,), id="cached-prefix-must-not-starve-new-numerics"),
        pytest.param((1,), 1, (0,), id="uncached-prefix"),
        pytest.param((), 1, (0,), id="stable-cap"),
        pytest.param((), 2, (0, 1), id="stable-order"),
        pytest.param((0,), 2, (1,), id="uncached-frontier-only"),
        pytest.param((0, 1), 1, (0,), id="all-cached-membership-fallback"),
    ),
)
def test_missing_graph_bindings_prioritize_unencoded_sources(
    reconciliation, cached_indexes, maximum_targets, expected_indexes
):
    c = reconciliation
    # A fresh Graph can lack every binding while canonical encoding rows survive.
    # Cached encodings retain real demands, but need no physical allocation.
    c.current.missing = tuple(reversed(c.full))
    c.current.reusable_rows = tuple(
        RegisteredEmbeddingRow(c.full[index].encoding, c.full[index].row_ref)
        for index in cached_indexes
    )
    c.app.maximum_targets = maximum_targets
    result = c.app.run_once()
    assert result.index_refresh_reason == (
        "REUSABLE_ENCODINGS_NOT_BOUND" if len(cached_indexes) == len(c.full) else None
    )
    assert result.missing_binding_count == len(c.full)
    assert result.selected_target_count == len(expected_indexes)
    _request, plan = read_plan(c, result)
    assert tuple(source.item_revision_id for source in plan.sources) == tuple(
        c.full[index].source.item_revision_id for index in expected_indexes
    )
    c.launcher.run.assert_not_called()


@pytest.mark.parametrize("state", ("FAILED", "COMPLETED"))
def test_original_terminal_intent_is_returned_without_head_rewind_or_new_command(
    reconciliation, state
):
    c = reconciliation
    c.current.bindings, c.current.missing = c.full, ()
    first = c.app.run_once()
    # Synthetic terminal history only, not a production completion/repair.
    with c.source.publisher.sessions.begin() as session:
        session.get(WorkflowInstanceRecord, first.workflow_id).state = state
        session.get(WorkflowCommandRecord, first.command_id).state = (
            "SUCCEEDED" if state == "COMPLETED" else "FAILED"
        )
    before, previous = counts(c), c.current.previous
    same = c.app.run_once()
    assert same.state is ReconciliationState.TERMINAL_INCOMPLETE
    assert same.workflow_id == first.workflow_id and same.command_id == first.command_id
    assert counts(c) == before and c.current.previous is previous
    c.launcher.run.assert_not_called()


def test_metadata_refresh_uses_full_available_subset_not_numeric_target_limit(reconciliation):
    c = reconciliation
    c.current.bindings, c.current.missing = c.full, ()
    result = c.app.run_once()
    assert result.index_refresh_reason == "MISSING_NAMESPACE_INDEX"
    assert result.selected_target_count == 2 > c.app.maximum_targets
    _request, plan = read_plan(c, result)
    assert tuple(s.item_revision_id for s in plan.sources) == tuple(
        b.source.item_revision_id for b in c.full
    )
    assert all(d.encoding in {b.encoding for b in c.full} for d in plan.demands)
    c.launcher.run.assert_not_called()


def test_refresh_excludes_new_missing_binding_until_next_numerical_batch(reconciliation):
    c = reconciliation
    c.current.bindings, c.current.missing = c.full[:1], c.full[1:]
    result = c.app.run_once()
    assert result.index_refresh_reason == "MISSING_NAMESPACE_INDEX"
    assert result.missing_binding_count == result.selected_target_count == 1
    _request, plan = read_plan(c, result)
    assert tuple(s.item_revision_id for s in plan.sources) == (c.full[0].source.item_revision_id,)


def test_current_available_encodings_complete_metadata_without_reservations_or_model(
    reconciliation, monkeypatch
):
    from contextlib import contextmanager

    from eom_workflow_runner import local_embedding_native_executor as native
    from eom_workflow_runner.readiness import RuntimeReadinessReport

    from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture

    c = reconciliation
    executor = c.app.executor
    f = carrier_fixture()
    request = c.source.scope.request
    monkeypatch.setattr(executor, "evaluate", lambda _: RuntimeReadinessReport(()))
    monkeypatch.setattr(
        executor, "_current", lambda *_a, **_k: SimpleNamespace(admission=c.source.scope)
    )
    monkeypatch.setattr(c.source.owner.catalog, "require_index_publication_scope", Mock())
    monkeypatch.setattr(
        c.source.owner.catalog,
        "prepare_mixed_index_basis",
        lambda *_: SimpleNamespace(
            reusable_rows=tuple(RegisteredEmbeddingRow(b.encoding, b.row_ref) for b in c.full)
        ),
    )
    allocation = native.NativeCoordinatorAllocation(
        index_producer=native.new_native_artifact_producer(),
        receipt_producer=native.new_native_artifact_producer(),
        created_at=c.source.scope.policy.created_at,
        source_commit="a" * 40,
    )
    coordinator = Mock()
    coordinator.read.return_value = SimpleNamespace(
        state="RUNNING", records=(SimpleNamespace(payload=allocation),)
    )
    monkeypatch.setattr(native, "NativeEmbeddingCoordinator", Mock(return_value=coordinator))
    monkeypatch.setattr(
        native,
        "create_native_embedding_launch",
        lambda *_a, **_k: SimpleNamespace(intent=f["association"].intent),
    )
    completion = Mock(return_value=f["output"])
    monkeypatch.setattr(executor._index_completion, "publish", completion)
    reservations = Mock(
        side_effect=AssertionError("metadata refresh must not reserve numerical work")
    )
    monkeypatch.setattr(executor, "_reservations", reservations)

    @contextmanager
    def fenced():
        yield Mock()

    workflow = SimpleNamespace(workflow_id="workflow_" + "1" * 32)
    step = SimpleNamespace(step_run_id="steprun_" + "2" * 32)
    lease = SimpleNamespace(
        command_id="wfcmd_" + "3" * 32, runner_id="synthetic", lease_generation=1
    )
    result = executor.execute(
        workflow=workflow,
        step=step,
        request=request,
        command_lease=lease,
        idempotency_key=f"local-embedding-step:{workflow.workflow_id}:encode_batch:1:{request.workflow_definition_sha256}",
        fenced_transaction=fenced,
    )
    assert result == f["output"]
    assert completion.call_args.args[7] == ()
    reservations.assert_not_called()
    c.launcher.run.assert_not_called()


def test_exact_current_membership_is_noop_and_empty_availability_never_fakes_index(reconciliation):
    c = reconciliation
    c.current.bindings, c.current.missing = c.full, ()
    c.current.previous = index_for(c.full, c.source.scope.plan)
    before = counts(c)
    result = c.app.run_once()
    assert result.state is ReconciliationState.UP_TO_DATE and result.index_refresh_reason is None
    assert counts(c) == before
    c.current.bindings = ()
    c.source.current = replace(c.source.current, entries=())
    result = c.app.run_once()
    assert result.state is ReconciliationState.WAITING_FOR_SOLUTION_REPORT
    assert result.workflow_id is None and counts(c) == before


def test_membership_removal_changes_selected_population_without_reencoding(reconciliation):
    c = reconciliation
    c.current.previous = index_for(c.full, c.source.scope.plan)
    c.current.bindings, c.current.missing = c.full[:1], ()
    kept = c.full[0].source.item_revision_id
    c.source.current = replace(
        c.source.current,
        sources=tuple(s for s in c.source.current.sources if s.item_revision_id == kept),
        entries=tuple(
            e
            for e in c.source.current.entries
            if e.profile.source_basis.source.item_revision_id == kept
        ),
        base_analysis_run_ids=tuple(
            (k, v) for k, v in c.source.current.base_analysis_run_ids if k == kept
        ),
    )
    result = c.app.run_once()
    assert result.index_refresh_reason == "INDEX_MEMBERSHIP_CHANGED"
    _request, plan = read_plan(c, result)
    assert len(plan.sources) == len(plan.demands) == 1


@pytest.mark.parametrize("fault", ("base", "definition", "grant", "late"))
def test_current_closure_failures_do_not_submit_partial_new_work(reconciliation, fault):
    c = reconciliation
    before = counts(c)
    if fault == "base":
        c.source.current = replace(c.source.current, base_analysis_run_ids=())
    elif fault == "definition":
        with c.source.publisher.sessions.begin() as session:
            row = session.scalar(select(WorkflowDefinitionRecord))
            row.active = False
    elif fault == "grant":
        c.source.deny = True
    else:
        controls = c.source.owner.resolve_reconciliation_controls
        calls = []

        def late(*args):
            calls.append(1)
            if len(calls) == 2:
                c.source.deny = True
            return controls(*args)

        c.source.owner.resolve_reconciliation_controls = late
    with pytest.raises(ValueError):
        c.app.run_once()
    assert counts(c) == before
    c.launcher.run.assert_not_called()


@pytest.mark.parametrize("fault", ("hash", "schema", "extra", "foreign", "duplicate", "budget"))
def test_mixed_refresh_comparison_revalidates_exact_pointers_and_rows(reconciliation, fault):
    c = reconciliation
    previous = index_for(c.full, c.source.scope.plan)
    bindings, sources = c.full, c.source.current.sources
    if fault in {"hash", "schema"}:
        field, value = (
            ("sha256", "sha256:" + "f" * 64)
            if fault == "hash"
            else ("schema_ref", "eom://schemas/knowledge/embedding-index-manifest/1.0")
        )
        previous = previous[0].model_copy(update={field: value}), previous[1]
    elif fault == "extra":
        bindings = (bindings[0].model_copy(update={"permissions": ["ADMIN"]}), *bindings[1:])
    elif fault == "foreign":
        sources = sources[:1]
    elif fault == "duplicate":
        bindings = (bindings[0], bindings[0])
    else:
        sources = sources * 513
    with pytest.raises(ValueError):
        mixed_index_membership_refresh_reason(
            eligible_sources=sources, available_bindings=bindings, previous=previous
        )
