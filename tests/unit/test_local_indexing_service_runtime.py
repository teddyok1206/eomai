"""Purpose-only construction/scheduling with explicit synthetic IO; no live grant."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_workflow_runner import engine as engine_module
from eom_workflow_runner import local_indexing_service_entry as entry
from eom_workflow_runner import native_cpu_scheduling_read as scheduling
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.catalog_port import WorkflowCatalogPort
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.local_embedding_admission import LocalEmbeddingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    ReconciliationState,
)
from eom_workflow_runner.local_indexing_service_runtime import (
    IndexingRoleExecutionDisabled,
    build_local_indexing_service_runtime,
)
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    NativeCommandActorSelection,
    peek_command_candidate,
)
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings
from sqlalchemy import create_engine


@pytest.fixture(autouse=True)
def synthetic_queue_read(monkeypatch):
    read = Mock(return_value=False)
    monkeypatch.setattr(scheduling, "should_defer_background_cpu_claim", read)
    return read


def scheduled_runtime(**values):
    leaf = SimpleNamespace(
        runner=values.pop("runner"),
        reconciliation=values.pop("reconciliation"),
        namespace=SimpleNamespace(view="CONTENT_ONLY"),
    )
    return SimpleNamespace(engine=Mock(), namespaces=(leaf,), **values)


def native_runner(monkeypatch, **changes):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(
        engine_module,
        "PlatformRoleJobExecutor",
        lambda *_a, **_k: pytest.fail("native owner must not build a Codex role executor"),
    )
    monkeypatch.setattr(
        WorkflowSettings,
        "load_runner",
        lambda *_a: pytest.fail("explicit native configuration must not read worker YAML"),
    )
    arguments = dict(
        catalog=Mock(spec=WorkflowCatalogPort),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(engine)
        ),
        readiness=IndexingRoleExecutionDisabled(),
        available_roles=frozenset(),
        local_embedding_owner=Mock(spec=LocalEmbeddingOwnerAdmission),
        local_embedding_executor=Mock(spec=LocalEmbeddingNativeExecutor),
        command_families=frozenset({CommandExecutionFamily.LOCAL_EMBEDDING}),
        command_actor_selection=NativeCommandActorSelection(
            "local_indexing_service", "localindexservice_" + "a" * 32
        ),
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=30,
            max_commands_per_run=64,
        ),
    )
    return WorkflowRunner(engine, **(arguments | changes))


def test_native_only_uses_no_fake_roles_codex_executor_or_readiness(monkeypatch):
    runner = native_runner(monkeypatch)
    assert runner.executor is None and not runner.available_roles
    assert not runner.readiness.evaluate().ready
    assert runner.command_families == frozenset({CommandExecutionFamily.LOCAL_EMBEDDING})


def test_native_only_peek_uses_same_queue_but_only_its_family_and_actor(monkeypatch):
    runner = native_runner(monkeypatch)
    peek = Mock(return_value=None)
    monkeypatch.setattr(engine_module, "peek_command_candidate", peek)
    assert runner.run_once() is None
    peek.assert_called_once()
    assert peek.call_args.kwargs["family"] is CommandExecutionFamily.LOCAL_EMBEDDING
    assert peek.call_args.kwargs["actor_selection"] == runner.command_actor_selection
    runner.local_embedding_executor.evaluate.assert_not_called()


@pytest.mark.parametrize(
    "fault", ["empty_families", "raw_family", "missing_owner", "role_selection"]
)
def test_unsupported_native_composition_is_explicit(monkeypatch, fault):
    changes = {
        "empty_families": {"command_families": frozenset()},
        "raw_family": {"command_families": frozenset({"LOCAL_EMBEDDING"})},
        "missing_owner": {"local_embedding_owner": None, "local_embedding_executor": None},
        "role_selection": {
            "command_families": frozenset(CommandExecutionFamily),
            "available_roles": frozenset({"authoring"}),
        },
    }[fault]
    with pytest.raises(ValueError):
        native_runner(monkeypatch, **changes)


def test_runtime_factory_requires_actual_capture_before_configuration_or_engine():
    with pytest.raises(ValueError, match="RUNTIME_UNAVAILABLE"):
        build_local_indexing_service_runtime(object(), object())


@pytest.mark.parametrize(
    "kind,identifier",
    [
        ("human", "operator_" + "b" * 32),
        ("local_indexing_service", "localindexservice_" + "c" * 32),
    ],
)
def test_actor_filter_is_selection_not_permission_and_one_bounded_statement(kind, identifier):
    selected = NativeCommandActorSelection(kind, identifier)
    session = Mock()
    session.execute.return_value.one_or_none.return_value = None
    assert (
        peek_command_candidate(
            session, family=CommandExecutionFamily.LOCAL_EMBEDDING, actor_selection=selected
        )
        is None
    )
    statement = session.execute.call_args.args[0]
    values = statement.compile().params
    assert kind in values.values() and identifier in values.values()
    assert statement._limit_clause.value == 1
    session.execute.assert_called_once()
    assert not hasattr(selected, "permissions")
    with pytest.raises(ValueError):
        peek_command_candidate(
            session, family=CommandExecutionFamily.ROLE, actor_selection=selected
        )


def test_developer_entry_denies_before_configuration_and_redacts_error(monkeypatch, capsys):
    def denied():
        raise ValueError("synthetic credential must never reach output")

    monkeypatch.setattr(entry, "_installed_site", denied)
    assert entry.main() == 1
    output = capsys.readouterr().out
    assert "synthetic credential" not in output
    assert "LOCAL_INDEXING_SERVICE_UNAVAILABLE" in output


def test_failure_detail_preserves_safe_context_even_when_traceback_display_is_suppressed():
    from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError

    try:
        try:
            raise PinnedArtifactResolutionError("SECRET source bytes and credential")
        except PinnedArtifactResolutionError:
            raise ValueError("SECRET wrapper payload") from None
    except ValueError as error:
        detail = entry._failure_detail(error)
    assert detail == {
        "cause_type": "PinnedArtifactResolutionError",
        "cause_code": None,
        "cause_site": None,
    }
    assert "SECRET" not in json.dumps(detail)


def test_failure_detail_bounds_exception_cycles_and_redacts_noncode_attributes():
    error = ValueError("SECRET")
    error.__context__ = error
    error.code = "SECRET value must not leak"
    assert entry._failure_detail(error) == {
        "cause_type": "ValueError",
        "cause_code": None,
        "cause_site": None,
    }


def test_failure_detail_exposes_only_uuid_pointer_ids_not_names_or_invalid_input():
    from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError

    error = PinnedArtifactResolutionError(
        "SECRET original filename",
        descriptor_reason="SCHEMA_MEDIA",
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
    )
    detail = entry._failure_detail(error)
    assert detail["cause_artifact_id"] == error.artifact_id
    assert detail["cause_artifact_revision_id"] == error.artifact_revision_id
    assert "SECRET" not in json.dumps(detail)
    error.artifact_id = "SECRET filename"
    assert "cause_artifact_id" not in entry._failure_detail(error)


def test_stop_after_idle_peek_does_not_start_new_observation():
    stop = Event()

    def idle():
        stop.set()
        return None

    runtime = scheduled_runtime(runner=SimpleNamespace(run_once=idle), reconciliation=Mock())
    entry.serve_local_indexing(runtime, stop)
    runtime.namespaces[0].reconciliation.run_once.assert_not_called()


@pytest.mark.parametrize("state", [True, "unavailable"])
def test_current_query_or_unknown_queue_defers_claim_and_discovery(
    monkeypatch, synthetic_queue_read, capsys, state
):
    stop = Event()
    if state == "unavailable":
        synthetic_queue_read.side_effect = scheduling.NativeCpuSchedulingReadUnavailable()
    else:
        synthetic_queue_read.return_value = True
    waits = []

    def wait(seconds):
        waits.append(seconds)
        stop.set()
        return True

    monkeypatch.setattr(stop, "wait", wait)
    runtime = scheduled_runtime(runner=Mock(), reconciliation=Mock())
    entry.serve_local_indexing(runtime, stop)
    assert waits == [5.0]
    runtime.namespaces[0].runner.run_once.assert_not_called()
    runtime.namespaces[0].reconciliation.run_once.assert_not_called()
    assert capsys.readouterr().out.count("LOCAL_INDEXING_CPU_ADMISSION_DEFERRED") == 1


def test_query_completion_resumes_same_background_namespace_without_new_queue(
    monkeypatch, synthetic_queue_read, capsys
):
    stop = Event()
    synthetic_queue_read.side_effect = [True, True, False]
    monkeypatch.setattr(stop, "wait", lambda _seconds: False)

    def finish():
        stop.set()
        return SimpleNamespace(workflow_id="original", command_id="original", state="SUCCEEDED")

    runtime = scheduled_runtime(runner=Mock(), reconciliation=Mock())
    runtime.namespaces[0].runner.run_once.side_effect = finish
    entry.serve_local_indexing(runtime, stop)
    output = capsys.readouterr().out
    assert output.count("LOCAL_INDEXING_CPU_ADMISSION_DEFERRED") == 1
    assert output.count("LOCAL_INDEXING_CPU_ADMISSION_RESUMED") == 1
    runtime.namespaces[0].runner.run_once.assert_called_once()
    runtime.namespaces[0].reconciliation.run_once.assert_not_called()


def test_stop_during_active_command_finishes_it_without_another_claim_or_discovery(capsys):
    stop = Event()
    command = SimpleNamespace(workflow_id="workflow", command_id="command", state="SUCCEEDED")

    def finish_current():
        stop.set()
        return command

    runtime = scheduled_runtime(runner=Mock(), reconciliation=Mock())
    runtime.namespaces[0].runner.run_once.side_effect = finish_current
    entry.serve_local_indexing(runtime, stop)
    runtime.namespaces[0].runner.run_once.assert_called_once()
    runtime.namespaces[0].reconciliation.run_once.assert_not_called()
    assert capsys.readouterr().out.count("LOCAL_INDEXING_COMMAND_OBSERVED") == 1


def test_queue_is_drained_before_reconciliation_without_independent_claim(capsys):
    stop = Event()
    command = SimpleNamespace(
        workflow_id="workflow_" + "a" * 32, command_id="wfcmd_" + "b" * 32, state="SUCCEEDED"
    )
    runner = Mock()
    runner.run_once.side_effect = [command, None]
    observation = LocalEmbeddingReconciliationResult(ReconciliationState.NO_PUBLISHED_GRAPH, None)

    def reconcile():
        stop.set()
        return observation

    runtime = scheduled_runtime(
        runner=runner,
        reconciliation=SimpleNamespace(run_once=reconcile),
        configuration=SimpleNamespace(poll_interval_seconds=60),
    )
    entry.serve_local_indexing(runtime, stop)
    events = capsys.readouterr().out
    assert events.index("COMMAND_OBSERVED") < events.index("RECONCILIATION_OBSERVED")
    assert runner.run_once.call_count == 2


def test_unchanged_reconciliation_does_not_spam_journal(monkeypatch, capsys):
    stop = Event()
    clock = [0.0]
    waits = []
    monkeypatch.setattr(entry.time, "monotonic", lambda: clock[0])

    def wait(seconds):
        waits.append(seconds)
        clock[0] += 60
        if len(waits) == 2:
            stop.set()

    monkeypatch.setattr(stop, "wait", wait)
    runtime = scheduled_runtime(
        runner=Mock(),
        reconciliation=Mock(),
        configuration=SimpleNamespace(poll_interval_seconds=60),
    )
    runtime.namespaces[0].runner.run_once.return_value = None
    runtime.namespaces[0].reconciliation.run_once.return_value = LocalEmbeddingReconciliationResult(
        ReconciliationState.NO_PUBLISHED_GRAPH, None
    )
    entry.serve_local_indexing(runtime, stop)
    assert runtime.namespaces[0].reconciliation.run_once.call_count == 2
    assert capsys.readouterr().out.count("RECONCILIATION_OBSERVED") == 1
    assert all(0 < seconds <= 5 for seconds in waits)


def test_packaged_unit_is_single_canonical_template_and_has_no_runtime_repo_or_slot():
    source = (
        Path(__file__).resolve().parents[2]
        / "services/workflow_runner/eom_workflow_runner/resources"
        / "eom-embedding-index-owner.service.in"
    )
    unit = source.read_text()
    executable = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "@SOURCE_COMMIT@" in executable
    assert "/home/eom/" not in executable and "codex" not in executable.lower()
    assert "Restart=no" in unit and "NoNewPrivileges=yes" in unit
    assert "PrivateDevices=yes" in unit and "IPAddressDeny=any" in unit
    assert "InaccessiblePaths=/etc/eom/secrets" in unit
    assert "EnvironmentFile=/etc/eom/secrets/catalog-manager.env" in unit
    assert "StandardInput=null" in unit
    assert "slot" not in unit.lower()
