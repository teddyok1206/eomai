"""Resource recovery does not disable guards, mutate success or dispatch duplicate work."""

import stat
import subprocess
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_orchestrator import background_storage as storage
from eom_orchestrator import host_package_maintenance as maintenance
from eom_orchestrator.database import recoverable_database_error_code
from sqlalchemy.exc import OperationalError

from tests.unit.test_creative_parallel_execution import driver_case


def db_error(state, *, invalidated=False):
    original = RuntimeError("password=not-for-logs; private SQL parameters")
    original.sqlstate = state
    return OperationalError(
        "private SQL", {"secret": "never emit"}, original, connection_invalidated=invalidated
    )


@pytest.mark.parametrize("state", ["53100", "08006", "40001", "40P01", "55P03", "53300", "57P01"])
def test_known_transport_transaction_or_resource_errors_have_only_safe_codes(state):
    code = recoverable_database_error_code(db_error(state))
    assert code and code.startswith("BACKGROUND_DATABASE_") and "private" not in code


@pytest.mark.parametrize("state", ["28P01", "42501", "23505", "42P01", "57014", "invalid", ""])
def test_permissions_constraints_schema_and_unspecified_cancellation_are_not_retried(state):
    assert recoverable_database_error_code(db_error(state, invalidated=True)) is None


def test_invalidated_transport_without_sqlstate_is_recoverable_but_arbitrary_errors_are_not():
    assert recoverable_database_error_code(db_error(None, invalidated=True))
    assert recoverable_database_error_code(db_error(None)) is None
    assert recoverable_database_error_code(RuntimeError("53100")) is None


def test_storage_reserve_boundary_and_missing_path_are_explicit(monkeypatch, tmp_path):
    usage = Mock(return_value=NS(free=storage.MIN_BACKGROUND_FREE_BYTES))
    monkeypatch.setattr(storage.shutil, "disk_usage", usage)
    storage.require_background_write_capacity(tmp_path)
    usage.return_value = NS(free=storage.MIN_BACKGROUND_FREE_BYTES - 1)
    with pytest.raises(storage.BackgroundStoragePressure):
        storage.require_background_write_capacity(tmp_path)
    usage.side_effect = FileNotFoundError("invalid configured state path")
    with pytest.raises(FileNotFoundError):
        storage.require_background_write_capacity(tmp_path)


@pytest.mark.parametrize(
    "error", [db_error("53100"), db_error("08006"), storage.BackgroundStoragePressure()]
)
def test_failed_publication_reuses_same_accepted_window_without_restarting_report_jobs(
    monkeypatch, error
):
    case = driver_case(monkeypatch)
    case.driver.advance_once()
    original = case.driver.publishing
    original[0].state = "VERIFIED"  # committed append, then connection lost during final reads
    case.executor.complete(error)
    with pytest.raises(type(error)):
        case.driver.advance_once()
    assert case.driver.verified_count == 0 and case.driver.publication is None
    assert all(source.state == "READY_TO_PUBLISH" for source in original)
    assert len(case.visited) == 6
    case.driver.advance_once()
    assert case.driver.publishing == original and case.executor.calls == 2
    assert len(case.visited) == 6  # no repeated extraction/model submission
    case.executor.complete()
    progress = case.driver.advance_once()
    assert progress.verified_count == 3
    case.driver.close()


def test_permanent_database_error_does_not_clear_publication_or_claim_more_sources(monkeypatch):
    case = driver_case(monkeypatch)
    case.driver.advance_once()
    case.executor.complete(db_error("42501"))
    with pytest.raises(OperationalError):
        case.driver.advance_once()
    assert case.driver.publication is not None and case.driver.verified_count == 0
    assert len(case.visited) == 6
    with pytest.raises(OperationalError):
        case.driver.close()


@pytest.mark.parametrize("states", [b"inactive\n\ninactive\n", b"failed\n\ninactive\n"])
def test_host_update_gate_allows_only_known_idle_states(monkeypatch, states):
    invoke = Mock(return_value=NS(returncode=0, stdout=states))
    monkeypatch.setattr(maintenance.subprocess, "run", invoke)
    maintenance.require_host_package_maintenance_idle()
    assert invoke.call_args.args[0][2:4] == ("apt-daily.service", "apt-daily-upgrade.service")


@pytest.mark.parametrize(
    "states",
    [
        b"active\ninactive\n",
        b"inactive\nactivating\n",
        b"inactive\n",
        b"unknown\ninactive\n",
        b"x" * 129,
    ],
)
def test_host_update_gate_does_not_capture_during_upgrade_or_unknown_observation(
    monkeypatch, states
):
    monkeypatch.setattr(
        maintenance.subprocess, "run", Mock(return_value=NS(returncode=0, stdout=states))
    )
    with pytest.raises(maintenance.HostPackageMaintenancePending):
        maintenance.require_host_package_maintenance_idle()


@pytest.mark.parametrize("error", [OSError("private"), subprocess.TimeoutExpired("systemctl", 3)])
def test_unavailable_host_maintenance_read_defers_without_exception_prose(monkeypatch, error):
    monkeypatch.setattr(maintenance.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(maintenance.HostPackageMaintenancePending) as caught:
        maintenance.require_host_package_maintenance_idle()
    assert str(caught.value) == maintenance.HostPackageMaintenancePending.code


@pytest.mark.parametrize(
    "error",
    [
        db_error("53100"),
        db_error("08006"),
        storage.BackgroundStoragePressure(),
        maintenance.HostPackageMaintenancePending(),
    ],
)
def test_index_resource_wait_reuses_same_runtime_and_resumes_instead_of_exiting(
    monkeypatch, capsys, error
):
    from eom_workflow_runner import local_indexing_service_entry as entry

    stopped = NS(value=False)
    stopped.is_set = lambda: stopped.value
    waits = []
    stopped.wait = waits.append
    runtime = object()

    def successful_same_runtime(actual, stop):
        assert actual is runtime and stop is stopped
        stopped.value = True

    calls = []

    def attempt(actual, stop):
        calls.append(actual)
        if len(calls) == 1:
            raise error
        successful_same_runtime(actual, stop)

    monkeypatch.setattr(entry, "serve_local_indexing", attempt)
    entry.serve_with_resource_recovery(runtime, stopped)
    assert calls == [runtime, runtime] and waits == [60]
    output = capsys.readouterr().out
    assert "LOCAL_INDEXING_RESOURCE_DEFERRED" in output and "private" not in output


@pytest.mark.parametrize("error", [db_error("42501"), ValueError("HASH_MISMATCH")])
def test_index_authority_and_hash_errors_still_stop_without_a_retry(monkeypatch, error):
    from eom_workflow_runner import local_indexing_service_entry as entry

    serve = Mock(side_effect=error)
    stop = NS(is_set=lambda: False, wait=Mock())
    monkeypatch.setattr(entry, "serve_local_indexing", serve)
    with pytest.raises(type(error)):
        entry.serve_with_resource_recovery(object(), stop)
    assert serve.call_count == 1
    stop.wait.assert_not_called()


@pytest.mark.parametrize("fault", ["space", "database"])
def test_creative_owner_waits_then_finishes_without_rebuilding_service_or_restarting_slots(
    monkeypatch, tmp_path, capsys, fault
):
    from eom_catalog_service import creative_learning_runner as runner
    from eom_catalog_service.creative_cohort_execution import CreativeCohortProgress

    cohort_id = "creativecohort_" + "a" * 32
    scope = NS(
        cohort_id=cohort_id,
        cohort=NS(cohort_id=cohort_id, targets=(object(),)),
        max_in_flight_sources=1,
    )
    progress = CreativeCohortProgress(
        cohort_id=cohort_id,
        target_count=1,
        verified_count=1,
        external_number=None,
        state="VERIFIED",
        workflow_id=None,
        item_revision_id=None,
        analysis_run_id=None,
        graph_snapshot_revision_id=None,
    )
    owner = Mock()
    owner.advance_once.side_effect = (
        [db_error("53100"), progress] if fault == "database" else [progress]
    )
    construct = Mock(return_value=owner)
    engine = Mock()
    stop = NS(is_set=lambda: False, wait=Mock())
    statuses = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["test", "--cohort-revision-id", "rev_" + "a" * 32, "--verified-limit", "1"],
    )
    monkeypatch.setattr(runner.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        runner.os, "fstat", lambda _fd: NS(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)
    )
    monkeypatch.setattr(runner, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(runner, "validate_state_root", Mock())
    monkeypatch.setattr(
        runner, "write_status", lambda _root, _cohort, value: statuses.append(value.copy())
    )
    monkeypatch.setattr(runner, "Event", lambda: stop)
    monkeypatch.setattr(runner.signal, "signal", Mock())
    monkeypatch.setattr(runner.Settings, "from_environment", Mock())
    monkeypatch.setattr(runner.CatalogSettings, "from_environment", Mock())
    monkeypatch.setattr(runner, "build_engine", lambda: engine)
    monkeypatch.setattr(runner, "CatalogArtifactService", Mock())
    monkeypatch.setattr(runner, "ControlFileSetPublisher", Mock())
    monkeypatch.setattr(runner, "read_creative_execution_scope", Mock(return_value=(scope, None)))
    monkeypatch.setattr(runner, "CreativeCohortExecutionService", construct)
    capacity = Mock(
        side_effect=[storage.BackgroundStoragePressure(), None] if fault == "space" else None
    )
    monkeypatch.setattr(runner, "require_background_write_capacity", capacity)
    runner.main()
    assert [v["state"] for v in statuses] == ["STARTING", "WAITING_FOR_RESOURCES", "COMPLETED"]
    assert statuses[1]["verified_count"] == 0
    construct.assert_called_once()
    stop.wait.assert_called_once_with(60)
    assert "private SQL" not in capsys.readouterr().out
