"""No-inference maintenance fencing and bounded systemd observation regressions."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_orchestrator import codex_compatibility_maintenance as maintenance
from eom_orchestrator.control_service import WORKER_HOST_CAPACITY_LOCK_ID, ControlPlaneError
from eom_orchestrator.models import Base
from eom_orchestrator.worker_systemd import SYSTEMCTL_ENV
from sqlalchemy import Connection, Engine
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import SQLAlchemyError


def _database(results: list[bool]) -> tuple[Engine, Mock]:
    engine = Mock(spec=Engine)
    engine.dialect = SimpleNamespace(name="postgresql")
    connection = Mock(spec=Connection)
    connection.closed = False
    connection.invalidated = False
    connection.scalar.side_effect = results
    engine.connect.return_value = connection
    return cast(Engine, engine), connection


def _quiescent_read() -> list[bool]:
    return [True, False, False, False, False, False]


def _producer_output(**changes: str) -> bytes:
    blocks: list[str] = []
    for identity in maintenance.CODEX_PRODUCER_UNITS:
        properties = {
            "Id": identity,
            "LoadState": "loaded",
            "ActiveState": "inactive",
            "SubState": "dead",
            "MainPID": "0",
            "Job": "",
            "NeedDaemonReload": "no",
        }
        if not blocks:
            properties.update(changes)
        blocks.append("\n".join(f"{key}={value}" for key, value in properties.items()))
    return ("\n\n".join(blocks) + "\n").encode()


def _mock_host(monkeypatch: pytest.MonkeyPatch, *outputs: bytes) -> Mock:
    run = Mock(side_effect=[subprocess.CompletedProcess((), 0, value, b"") for value in outputs])
    monkeypatch.setattr(subprocess, "run", run)
    return run


def test_session_lock_and_each_read_transaction_finish_before_the_host_probe() -> None:
    engine, connection = _database([True, *_quiescent_read(), *_quiescent_read(), True])
    host = Mock()
    with maintenance.CodexCompatibilityMaintenance(engine, host_reader=host) as fence:
        assert connection.commit.call_count == 2
        fence.assert_quiescent()
        assert connection.commit.call_count == 3
    assert host.call_count == 2
    assert connection.commit.call_count == 4
    connection.close.assert_called_once()
    connection.invalidate.assert_not_called()
    statements = [str(call.args[0]) for call in connection.scalar.call_args_list]
    assert all(statement.startswith("SELECT") for statement in statements)
    assert "pg_try_advisory_lock" in statements[0]
    assert "pg_advisory_unlock" in statements[-1]
    ownership = connection.scalar.call_args_list[1]
    assert ownership.args[1] == {
        "classid": WORKER_HOST_CAPACITY_LOCK_ID >> 32,
        "objid": WORKER_HOST_CAPACITY_LOCK_ID & 0xFFFFFFFF,
    }


def test_read_only_pre_stop_check_reuses_work_queries_without_a_session_lock() -> None:
    engine, connection = _database([False] * 5)
    cast(Mock, engine.connect).return_value = nullcontext(connection)
    maintenance.assert_codex_compatibility_database_quiescent(engine)
    connection.commit.assert_called_once()
    assert connection.scalar.call_count == 5
    assert all(
        str(call.args[0]).startswith("SELECT EXISTS") for call in connection.scalar.call_args_list
    )
    connection.invalidate.assert_not_called()


def test_enrollment_reader_uses_the_same_owned_host_fence_without_stopping_producers() -> None:
    engine, connection = _database([True, True, True, True])
    database_reader = Mock()
    host_reader = Mock()
    with maintenance.CodexCompatibilityMaintenance(
        engine, host_reader=host_reader, database_reader=database_reader
    ) as fence:
        fence.assert_quiescent()
    assert database_reader.call_count == host_reader.call_count == 2
    assert all(call.args == (connection,) for call in database_reader.call_args_list)
    assert "pg_try_advisory_lock" in str(connection.scalar.call_args_list[0].args[0])
    assert "pg_advisory_unlock" in str(connection.scalar.call_args_list[-1].args[0])


@pytest.mark.parametrize(
    ("position", "code"),
    [
        (0, "CODEX_COMPATIBILITY_LEASE_BUSY"),
        (1, "CODEX_COMPATIBILITY_CONTROL_BUSY"),
        (2, "CODEX_COMPATIBILITY_JOB_BUSY"),
        (3, "CODEX_COMPATIBILITY_CHAT_BUSY"),
        (4, "CODEX_COMPATIBILITY_CHAT_BUSY"),
    ],
)
def test_pre_stop_read_cannot_call_a_busy_projection_quiet(position: int, code: str) -> None:
    engine, connection = _database([False] * position + [True])
    cast(Mock, engine.connect).return_value = nullcontext(connection)
    with pytest.raises(ControlPlaneError) as error:
        maintenance.assert_codex_compatibility_database_quiescent(engine)
    assert error.value.code == code
    connection.commit.assert_not_called()


def test_pre_stop_connection_failure_is_sanitized() -> None:
    engine, _ = _database([])
    cast(Mock, engine.connect).side_effect = SQLAlchemyError("sensitive connection detail")
    with pytest.raises(ControlPlaneError) as error:
        maintenance.assert_codex_compatibility_database_quiescent(engine)
    assert error.value.code == "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE"
    assert "sensitive" not in str(error.value)


def test_workers_only_pre_stop_check_does_not_require_idle_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _mock_host(monkeypatch, b"")
    maintenance.assert_codex_workers_quiescent()
    run.assert_called_once()
    assert run.call_args.args[0][1] == "list-units"


def test_historical_projection_uses_indexed_canonical_links_without_runner_import() -> None:
    # Composition owns model registration; this test registers that adapter, not the fence.
    from eom_workflow_runner import models as workflow_models
    from sqlalchemy import select

    statement = str(
        select(maintenance._executable_jobs_exist()).compile(
            dialect=cast(Callable[[], Dialect], dialect)(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "jobs.status IN ('CLAIMED', 'RUNNING')" in statement
    assert "jobs.request ->> 'workflow_id'" in statement
    assert "jobs.request ->> 'step_run_id'" in statement
    assert "LEFT OUTER JOIN workflow_instances" in statement
    assert "maintenance_parent.workflow_id IS NULL" in statement
    assert "maintenance_parent_command.state IN ('PENDING', 'LEASED', 'PROCESSING')" in statement
    assert workflow_models.WorkflowStepRunRecord.__table__.c.platform_job_id.index is True
    assert workflow_models.WorkflowCommandRecord.__table__.c.workflow_id.index is True


def test_incomplete_composition_cannot_prove_a_historical_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import select

    monkeypatch.setattr(Base, "metadata", SimpleNamespace(tables={}))
    statement = str(
        select(maintenance._executable_jobs_exist()).compile(
            dialect=cast(Callable[[], Dialect], dialect)(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "'QUEUED', 'CLAIMED', 'RUNNING'" in statement
    assert "workflow_step_runs" not in statement


def test_busy_host_lock_never_observes_or_launches_workers() -> None:
    engine, connection = _database([False])
    host = Mock()
    with (
        pytest.raises(ControlPlaneError, match="already reserved") as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=host),
    ):
        pytest.fail("busy host cannot enter")
    assert error.value.code == "CODEX_COMPATIBILITY_FENCE_BUSY"
    host.assert_not_called()
    connection.close.assert_called_once()
    assert connection.scalar.call_count == 1


@pytest.mark.parametrize(
    ("position", "expected_code"),
    [
        (0, "CODEX_COMPATIBILITY_LEASE_BUSY"),
        (1, "CODEX_COMPATIBILITY_CONTROL_BUSY"),
        (2, "CODEX_COMPATIBILITY_JOB_BUSY"),
        (3, "CODEX_COMPATIBILITY_CHAT_BUSY"),
        (4, "CODEX_COMPATIBILITY_CHAT_BUSY"),
    ],
)
def test_existing_work_rejects_diagnostics_without_row_mutation(
    position: int, expected_code: str
) -> None:
    results = [True, True, *([False] * position), True, True]
    engine, connection = _database(results)
    host = Mock()
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=host),
    ):
        pytest.fail("busy work cannot enter")
    assert error.value.code == expected_code
    host.assert_not_called()
    connection.rollback.assert_called()
    connection.close.assert_called_once()
    assert "pg_advisory_unlock" in str(connection.scalar.call_args.args[0])
    assert all(str(call.args[0]).startswith("SELECT") for call in connection.scalar.call_args_list)


def test_recheck_detects_new_work_and_stops_subsequent_launches() -> None:
    engine, connection = _database([True, *_quiescent_read(), True, True, True])
    host = Mock()
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=host) as fence,
    ):
        fence.assert_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_LEASE_BUSY"
    assert host.call_count == 1
    connection.close.assert_called_once()


def test_lost_session_or_advisory_lock_never_reacquires_implicitly() -> None:
    engine, connection = _database([True, *_quiescent_read(), False, False])
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()) as fence,
    ):
        fence.assert_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_FENCE_LOST"
    connection.invalidate.assert_called_once()
    assert (
        sum(
            "pg_try_advisory_lock" in str(call.args[0]) for call in connection.scalar.call_args_list
        )
        == 1
    )


def test_invalidation_after_entry_cannot_authorize_a_launch() -> None:
    engine, connection = _database([True, *_quiescent_read()])
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()) as fence,
    ):
        connection.invalidated = True
        fence.assert_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_FENCE_LOST"
    connection.invalidate.assert_called_once()
    connection.close.assert_called_once()


def test_invalid_database_projection_fails_closed() -> None:
    engine, connection = _database([True, True, True])
    connection.scalar.side_effect = [True, True, None, True]
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pytest.fail("invalid database evidence cannot enter")
    assert error.value.code == "CODEX_COMPATIBILITY_DATABASE_INVALID"


def test_failed_read_is_sanitized_and_unlocks_the_host() -> None:
    engine, connection = _database([])
    connection.scalar.side_effect = [True, SQLAlchemyError("sensitive connection detail"), True]
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pytest.fail("failed read cannot enter")
    assert error.value.code == "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE"
    assert "sensitive" not in str(error.value)
    connection.close.assert_called_once()


def test_connect_failure_exposes_only_stable_sanitized_error() -> None:
    engine, _connection = _database([])
    cast(Mock, engine.connect).side_effect = SQLAlchemyError("sensitive connection detail")
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pytest.fail("failed connection cannot enter")
    assert error.value.code == "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE"
    assert "sensitive" not in str(error.value)


def test_uncertain_lock_acquisition_discards_the_physical_session() -> None:
    engine, connection = _database([])
    connection.scalar.side_effect = SQLAlchemyError("sensitive lock detail")
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pytest.fail("uncertain lock cannot enter")
    assert error.value.code == "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE"
    connection.invalidate.assert_called_once()
    connection.close.assert_called_once()


def test_failed_read_rollback_never_masks_the_sanitized_error() -> None:
    engine, connection = _database([])
    connection.scalar.side_effect = [True, SQLAlchemyError("sensitive connection detail")]
    connection.rollback.side_effect = SQLAlchemyError("sensitive rollback detail")
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pytest.fail("failed read cannot enter")
    assert error.value.code == "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE"
    assert "sensitive" not in str(error.value)
    connection.invalidate.assert_called()
    connection.close.assert_called_once()


def test_interrupted_unlock_never_returns_a_locked_session_to_the_pool() -> None:
    engine, connection = _database([])
    connection.scalar.side_effect = [True, *_quiescent_read(), KeyboardInterrupt()]
    with (
        pytest.raises(KeyboardInterrupt),
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pass
    connection.invalidate.assert_called_once()
    connection.close.assert_called_once()


def test_unlock_failure_discards_physical_connection_and_is_an_explicit_error() -> None:
    engine, connection = _database([True, *_quiescent_read(), False])
    with (
        pytest.raises(ControlPlaneError) as error,
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        pass
    assert error.value.code == "CODEX_COMPATIBILITY_FENCE_LOST"
    connection.invalidate.assert_called_once()
    connection.close.assert_called_once()


def test_failed_unlock_does_not_replace_original_operation_error() -> None:
    engine, connection = _database([True, *_quiescent_read(), False])
    with (
        pytest.raises(ValueError, match="original failure"),
        maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()),
    ):
        raise ValueError("original failure")
    connection.invalidate.assert_called_once()
    connection.close.assert_called_once()


def test_nested_context_does_not_release_outer_lock() -> None:
    engine, connection = _database([True, *_quiescent_read(), True])
    with maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock()) as fence:
        with pytest.raises(ControlPlaneError) as error, fence:
            pytest.fail("nested fence cannot enter")
        assert error.value.code == "CODEX_COMPATIBILITY_FENCE_ACTIVE"
        connection.close.assert_not_called()
    connection.close.assert_called_once()


def test_without_context_and_non_postgresql_are_explicit_errors() -> None:
    engine, connection = _database([])
    fence = maintenance.CodexCompatibilityMaintenance(engine, host_reader=Mock())
    with pytest.raises(ControlPlaneError) as error:
        fence.assert_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_FENCE_LOST"
    engine.dialect.name = "sqlite"
    with pytest.raises(ControlPlaneError) as error, fence:
        pytest.fail("SQLite cannot fence PostgreSQL claims")
    assert error.value.code == "CODEX_COMPATIBILITY_BACKEND_UNSUPPORTED"
    connection.scalar.assert_not_called()


def test_host_reader_uses_only_fixed_bounded_read_only_systemctl_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _mock_host(monkeypatch, _producer_output(), b"")
    maintenance.assert_codex_producers_quiescent()
    assert run.call_count == 2
    for call in run.call_args_list:
        assert call.args[0][0] == "/usr/bin/systemctl"
        assert call.args[0][1] in {"show", "list-units"}
        assert call.kwargs["timeout"] == 5
        assert call.kwargs["stdin"] == subprocess.DEVNULL
        assert call.kwargs["env"] == SYSTEMCTL_ENV
    assert "eom-worker-*.service" in run.call_args.args[0]


@pytest.mark.parametrize(
    "change",
    [
        {"ActiveState": "active"},
        {"ActiveState": "activating"},
        {"SubState": "running"},
        {"MainPID": "123"},
        {"Job": "123/eom-workflow-runner.service/start"},
        {"NeedDaemonReload": "yes"},
        {"LoadState": "not-found"},
    ],
)
def test_active_or_unproven_producer_cannot_pass(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, str]
) -> None:
    run = _mock_host(monkeypatch, _producer_output(**change))
    with pytest.raises(ControlPlaneError) as error:
        maintenance.assert_codex_producers_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_PRODUCER_BUSY"
    assert run.call_count == 1


@pytest.mark.parametrize(
    "output",
    [
        b"",
        _producer_output().replace(b"MainPID=0\n", b"", 1),
        _producer_output() + _producer_output().split(b"\n\n")[0],
        _producer_output().replace(b"Id=eom-workflow-runner.service", b"Id=untrusted.service"),
        _producer_output().replace(b"MainPID=0", b"MainPID=0\nUnexpected=credential"),
        _producer_output().replace(b"MainPID=0", b"MainPID=0\nMainPID=0"),
        b"\xff",
    ],
)
def test_incomplete_duplicate_or_unexpected_host_evidence_is_rejected(
    monkeypatch: pytest.MonkeyPatch, output: bytes
) -> None:
    _mock_host(monkeypatch, output)
    with pytest.raises(ControlPlaneError) as error:
        maintenance.assert_codex_producers_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_UNIT_INVALID"


@pytest.mark.parametrize(
    "unit",
    [
        "eom-worker-01@job_" + "a" * 32 + ".service",
        "eom-worker-support-06@job_" + "a" * 32 + ".service",
        "eom-worker-document-review-06@job_" + "a" * 32 + ".service",
        "eom-worker-usage-02@codexcmd_" + "a" * 32 + "-authbinding_" + "b" * 32 + ".service",
        "eom-worker-login-03@authflow_" + "a" * 32 + ".service",
        "eom-worker-unknown@unexpected.service",
        "eom-worker@01.service",
    ],
)
def test_orphan_helper_or_specialized_worker_prevents_launch(
    monkeypatch: pytest.MonkeyPatch, unit: str
) -> None:
    _mock_host(monkeypatch, _producer_output(), f"{unit} loaded active running worker\n".encode())
    with pytest.raises(ControlPlaneError) as error:
        maintenance.assert_codex_producers_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_WORKER_BUSY"


@pytest.mark.parametrize("failure", ["exit", "stderr", "large", "timeout"])
def test_unavailable_or_unbounded_unit_evidence_never_passes(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "timeout":
        run = Mock(side_effect=subprocess.TimeoutExpired("/usr/bin/systemctl", 5))
    else:
        run = Mock(
            return_value=subprocess.CompletedProcess(
                (),
                1 if failure == "exit" else 0,
                b"x" * (maintenance._MAX_UNIT_OUTPUT_BYTES + 1) if failure == "large" else b"",
                b"private detail" if failure == "stderr" else b"",
            )
        )
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ControlPlaneError) as error:
        maintenance.assert_codex_producers_quiescent()
    assert error.value.code == "CODEX_COMPATIBILITY_UNIT_UNAVAILABLE"
    assert "private" not in str(error.value)
