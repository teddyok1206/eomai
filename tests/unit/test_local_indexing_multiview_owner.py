"""Closed selection and synthetic queue/scheduler IO, not live source/model approval."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.local_indexing_owner_configuration import (
    LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256,
    LOCAL_INDEXING_OWNER_SCHEMA_SHA256,
    LocalIndexingMultiviewOwnerConfiguration,
    LocalIndexingOwnerConfiguration,
    local_indexing_owner_configuration_bytes,
    parse_local_indexing_owner_configuration,
)
from eom_workflow_runner import local_indexing_service_entry as entry
from eom_workflow_runner import local_indexing_service_runtime as composition
from eom_workflow_runner import native_cpu_scheduling_read as scheduling
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    ReconciliationState,
)
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    NativeCommandActorSelection,
    peek_command_candidate,
)
from sqlalchemy.dialects import postgresql

from tests.unit.test_local_indexing_owner_configuration import document

ROOT = Path(__file__).resolve().parents[2]
VIEWS = ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY")


def multiview_document():
    body = document()
    body["schema_version"] = "local-indexing-owner-configuration/2.0"
    body["namespace"]["view"] = VIEWS[0]
    body["additional_namespaces"] = [body["namespace"] | {"view": view} for view in VIEWS[1:]]
    return body


def test_v2_schema_mirror_and_wire_roundtrip_leave_v1_bytes_unchanged():
    for version, expected in (
        (1, LOCAL_INDEXING_OWNER_SCHEMA_SHA256),
        (2, LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256),
    ):
        name = f"local-indexing-owner-configuration-v{version}.schema.json"
        raw = (ROOT / "schemas/workflow" / name).read_bytes()
        assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        assert sha256_bytes(raw) == expected
    old = canonical_json_bytes(document())
    parsed = parse_local_indexing_owner_configuration(old)
    assert type(parsed) is LocalIndexingOwnerConfiguration
    assert parsed.namespaces == (parsed.namespace,)
    assert local_indexing_owner_configuration_bytes(parsed) == old
    raw = canonical_json_bytes(multiview_document())
    parsed = parse_local_indexing_owner_configuration(raw)
    assert type(parsed) is LocalIndexingMultiviewOwnerConfiguration
    assert tuple(namespace.view for namespace in parsed.namespaces) == VIEWS
    assert local_indexing_owner_configuration_bytes(parsed) == raw
    assert not hasattr(parsed, "permissions")


@pytest.mark.parametrize(
    "fault",
    (
        "empty",
        "too_many",
        "duplicate",
        "duplicate_primary",
        "space",
        "recipe",
        "projection",
        "partition",
        "population",
        "roles",
        "nested_extra",
        "boolean",
        "v1_extra",
    ),
)
def test_closed_v2_rejects_mixed_namespaces_and_caller_authority(fault):
    body = multiview_document()
    extra = body["additional_namespaces"]
    if fault == "empty":
        body["additional_namespaces"] = []
    elif fault == "too_many":
        extra.append(deepcopy(body["namespace"]))
    elif fault == "duplicate":
        extra[1] = deepcopy(extra[0])
    elif fault == "duplicate_primary":
        extra[0] = deepcopy(body["namespace"])
    elif fault in {"space", "recipe"}:
        extra[0][fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault == "projection":
        extra[0]["projection_version"] = "latest"
    elif fault == "partition":
        extra[0]["storage_partition"] = "another.valid.partition"
    elif fault == "population":
        old = extra[0]["population_scope"]
        extra[0]["population_scope"] = (
            "ALL_ADMITTED_GRAPH_ITEMS"
            if old != "ALL_ADMITTED_GRAPH_ITEMS"
            else "OCCURRENCE_BACKED_PAST_EXAM"
        )
    elif fault == "roles":
        body["roles"] = ["ADMIN"]
    elif fault == "nested_extra":
        extra[0]["permission"] = "ADMIN"
    elif fault == "boolean":
        body["maximum_targets"] = True
    else:
        body["schema_version"] = "local-indexing-owner-configuration/1.0"
    with pytest.raises(ValueError):
        parse_local_indexing_owner_configuration(canonical_json_bytes(body))


def test_model_copy_cannot_smuggle_unvalidated_nested_namespace():
    selected = LocalIndexingMultiviewOwnerConfiguration.model_validate(multiview_document())
    extra = selected.additional_namespaces[0].model_copy(update={"permissions": ["ADMIN"]})
    copied = selected.model_copy(update={"additional_namespaces": (extra,)})
    with pytest.raises(ValueError):
        local_indexing_owner_configuration_bytes(copied)


@pytest.mark.parametrize("view", VIEWS)
def test_each_leaf_uses_exact_namespace_with_shared_publisher_authority_and_launcher(
    monkeypatch, view
):
    selected = LocalIndexingMultiviewOwnerConfiguration.model_validate(multiview_document())
    namespace = next(value for value in selected.namespaces if value.view == view)
    engine, publisher, authority, launcher = Mock(), Mock(), Mock(), Mock()
    publisher.sessions.begin.return_value.__enter__ = Mock(return_value=Mock())
    publisher.sessions.begin.return_value.__exit__ = Mock(return_value=False)
    owner = Mock()
    owner.current_reconciliation_lookup.return_value = "synthetic current graph lookup"
    owner_factory = Mock(return_value=owner)
    executor_factory, runner_factory, reconciliation_factory = Mock(), Mock(), Mock()
    monkeypatch.setattr(
        composition.CatalogLocalEmbeddingOwnerAdmission, "for_indexing_service", owner_factory
    )
    monkeypatch.setattr(composition, "CatalogNativeEmbeddingExecutor", executor_factory)
    monkeypatch.setattr(composition, "WorkflowRunner", runner_factory)
    monkeypatch.setattr(composition, "LocalEmbeddingServiceReconciliation", reconciliation_factory)
    pin = SimpleNamespace(
        service=SimpleNamespace(service_id="localindexservice_" + "a" * 32),
        runtime_source_commit="f" * 40,
    )
    result = composition._build_namespace_runtime(
        engine, publisher, authority, selected, namespace, pin, Mock(), launcher
    )
    assert result.namespace == namespace
    assert owner_factory.call_args.args[1].registry.namespace == namespace
    assert owner_factory.call_args.kwargs["source_authority"] is authority
    owner.resolve_reconciliation_controls.assert_called_once()
    assert executor_factory.call_args.kwargs["publisher"] is publisher
    backend = executor_factory.call_args.kwargs["execution_backend"]
    assert type(backend) is composition.FixedCpuDocumentEmbeddingExecution
    assert backend.launcher is launcher
    assert runner_factory.call_args.kwargs["local_embedding_owner"] is owner
    assert runner_factory.call_args.kwargs["command_actor_selection"].namespace == namespace
    assert reconciliation_factory.call_args.kwargs["maximum_targets"] == selected.maximum_targets
    assert result.runner is runner_factory.return_value
    assert result.reconciliation is reconciliation_factory.return_value


def test_exact_namespace_queue_predicate_is_selection_not_permission():
    namespace = EmbeddingIndexNamespace.model_validate(multiview_document()["namespace"])
    selection = NativeCommandActorSelection(
        "local_indexing_service", "localindexservice_" + "a" * 32, namespace
    )
    session = Mock()
    session.execute.return_value.one_or_none.return_value = None
    assert (
        peek_command_candidate(
            session, family=CommandExecutionFamily.LOCAL_EMBEDDING, actor_selection=selection
        )
        is None
    )
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert namespace.model_dump(mode="json") in compiled.params.values()
    assert "initial_request" in str(compiled) and "JSONB" in str(compiled)
    assert statement._limit_clause.value == 1
    session.execute.assert_called_once()
    with pytest.raises(ValueError):
        peek_command_candidate(
            session, family=CommandExecutionFamily.REFERENCE_QUERY, actor_selection=selection
        )
    with pytest.raises(ValueError):
        NativeCommandActorSelection("human", "operator_" + "b" * 32, namespace)
    with pytest.raises(ValueError):
        NativeCommandActorSelection(
            "local_indexing_service",
            selection.actor_id,
            namespace.model_copy(update={"permissions": ["ADMIN"]}),
        )


def schedule(monkeypatch, stop, *, busy=False):
    clock = [0.0]
    # These scheduler tests isolate round-robin behavior, not the separate SQL quiet gate.
    monkeypatch.setattr(scheduling, "should_defer_background_cpu_claim", Mock(return_value=False))
    monkeypatch.setattr(entry.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(stop, "wait", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    leaves = []
    for index, view in enumerate(VIEWS):
        runner = Mock()
        runner.run_once.return_value = (
            SimpleNamespace(workflow_id="workflow", command_id="command", state="SUCCEEDED")
            if busy and index == 0
            else None
        )
        reconciliation = Mock()
        reconciliation.run_once.return_value = LocalEmbeddingReconciliationResult(
            ReconciliationState.UP_TO_DATE, "graph"
        )
        leaves.append(
            composition.LocalIndexingNamespaceRuntime(
                namespace=SimpleNamespace(view=view), runner=runner, reconciliation=reconciliation
            )
        )
    return SimpleNamespace(
        engine=Mock(),
        namespaces=tuple(leaves),
        configuration=SimpleNamespace(poll_interval_seconds=30),
    ), clock


def test_busy_primary_does_not_starve_other_view_discovery(monkeypatch, capsys):
    stop = Event()
    runtime, _clock = schedule(monkeypatch, stop, busy=True)
    observed = runtime.namespaces[2].reconciliation.run_once.return_value
    runtime.namespaces[2].reconciliation.run_once.side_effect = lambda: (stop.set(), observed)[1]
    entry.serve_local_indexing(runtime, stop)
    for leaf in runtime.namespaces:
        leaf.runner.run_once.assert_called_once()
    runtime.namespaces[0].reconciliation.run_once.assert_not_called()
    for leaf in runtime.namespaces[1:]:
        leaf.reconciliation.run_once.assert_called_once()
    assert capsys.readouterr().out.count("RECONCILIATION_OBSERVED") == 2


def test_independent_deadlines_and_per_view_journal_dedup(monkeypatch, capsys):
    stop = Event()
    runtime, clock = schedule(monkeypatch, stop)
    original_wait = stop.wait

    def wait(seconds):
        original_wait(seconds)
        if clock[0] >= 70:
            stop.set()

    monkeypatch.setattr(stop, "wait", wait)
    entry.serve_local_indexing(runtime, stop)
    assert all(leaf.reconciliation.run_once.call_count >= 2 for leaf in runtime.namespaces)
    assert capsys.readouterr().out.count("RECONCILIATION_OBSERVED") == 3


def test_stop_during_one_view_command_does_not_claim_next_view(monkeypatch):
    stop = Event()
    runtime, _clock = schedule(monkeypatch, stop, busy=True)
    command = runtime.namespaces[0].runner.run_once.return_value
    runtime.namespaces[0].runner.run_once.side_effect = lambda: (stop.set(), command)[1]
    entry.serve_local_indexing(runtime, stop)
    for leaf in runtime.namespaces[1:]:
        leaf.runner.run_once.assert_not_called()
    assert all(leaf.reconciliation.run_once.call_count == 0 for leaf in runtime.namespaces)
