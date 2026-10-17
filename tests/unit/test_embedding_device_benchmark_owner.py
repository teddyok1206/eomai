"""Synthetic runtime/control/capacity on local SQLite; NOT installed admission or inference."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from eom_orchestrator import embedding_device_benchmark_owner as module
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from sqlalchemy import event, func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_benchmark_launch_history import SyntheticResultReader, receipt_for


class SyntheticOwnerAdmission(SyntheticBenchmarkAdmission):
    def __init__(self, request, inputs, reader):
        super().__init__(request, inputs)
        self.reader, self.active = reader, 0

    @contextmanager
    def admit_in_session(self, session, request):
        with super().admit_in_session(session, request) as inputs:
            self.active += 1
            try:
                yield inputs
            finally:
                self.active -= 1

    def admit_execution_in_session(self, session, request):
        return self.admit_in_session(session, request)

    def read_in_session(self, session, request, pointer):
        assert self.active > 0
        return self.reader.read_in_session(session, request, pointer)


class SyntheticExecution:
    def __init__(self, state):
        self.state, self.calls, self.preflights = state, [], 0
        self.fail_ordinal = None
        self.failed_result = False
        self.revoke_after_output = False

    def assert_installed(self, request):
        assert request == self.state.request and self.state.admission.active == 0
        self.preflights += 1

    def run_and_publish(self, invocation, inputs, authorization):
        assert self.state.capacity[0] and self.state.admission.active == 0
        assert inputs == self.state.inputs
        self.calls.append(invocation)
        authorization.assert_current()
        assert self.state.admission.active == 0
        if invocation.launch_ordinal == self.fail_ordinal:
            raise TimeoutError("synthetic output/termination uncertain")
        receipt = receipt_for(self.state.storage, invocation, failed=self.failed_result)
        authorization.assert_current()
        if self.revoke_after_output:
            self.state.admission.late_error = ValueError("SYNTHETIC_EXPIRED_AFTER_PUBLICATION")
        return receipt


@pytest.fixture
def owner_case(tmp_path, monkeypatch):
    publisher, engine = _publisher(tmp_path)
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.create_function(
            "pg_try_advisory_xact_lock", 1, lambda _: True
        ),
    )
    engine.dispose()
    request, inputs = benchmark_case()
    reader = SyntheticResultReader()
    admission = SyntheticOwnerAdmission(request, inputs, reader)
    capacity = [False]

    @contextmanager
    def synthetic_capacity():
        assert not capacity[0]
        capacity[0] = True
        try:
            yield
        finally:
            capacity[0] = False

    monkeypatch.setattr(module, "native_cpu_capacity", synthetic_capacity)
    monkeypatch.setattr(module, "require_no_active_native_cpu_execution", lambda: None)
    state = SimpleNamespace(
        sessions=publisher.sessions,
        request=request,
        inputs=inputs,
        admission=admission,
        reader=reader,
        capacity=capacity,
        engine=engine,
    )
    state.execution = SyntheticExecution(state)
    state.owner = BenchmarkExecutionOwner(
        state.sessions, admission=admission, execution=state.execution
    )
    state.storage = (state.sessions, admission, reader, state.owner.journal, None)
    yield state
    engine.dispose()


def test_complete_series_uses_one_job_six_original_executions_and_no_replay_dispatch(owner_case):
    case = owner_case
    result = case.owner.run_launches(case.request)
    assert result.dispatch_count == 6 and result.state == "VALIDATING_RESULT"
    assert len(result.receipts) == len(case.execution.calls) == 6
    assert [value.device for value in case.execution.calls] == [
        "CPU",
        "CUDA",
        "CUDA",
        "CPU",
        "CPU",
        "CUDA",
    ]
    assert {value.job_id for value in case.execution.calls} == {result.job_id}
    assert len({value.execution_id for value in case.execution.calls}) == 6
    replay = case.owner.run_launches(case.request)
    assert replay.job_id == result.job_id and replay.receipts == result.receipts
    assert replay.dispatch_count == 0 and len(case.execution.calls) == 6
    assert not case.capacity[0] and case.admission.active == 0
    case.owner.execution = None
    assert case.owner.run_launches(case.request) == replay
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert session.get(JobRecord, result.job_id).status == "VALIDATING_RESULT"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 18


@pytest.mark.parametrize("ordinal", (1, 2, 6))
def test_timeout_keeps_original_unresolved_invocation_and_blocks_automatic_restart(
    owner_case, ordinal
):
    case = owner_case
    case.execution.fail_ordinal = ordinal
    with pytest.raises(ValueError, match="EXECUTION_UNCERTAIN"):
        case.owner.run_launches(case.request)
    original = tuple(case.execution.calls)
    case.execution.fail_ordinal = None
    with pytest.raises(ValueError, match="ORIGINAL_EXECUTION_UNRESOLVED"):
        case.owner.run_launches(case.request)
    assert tuple(case.execution.calls) == original and len(original) == ordinal
    assert not case.capacity[0]
    with case.sessions() as session, session.begin():
        jobs = list(session.scalars(select(JobRecord)))
        assert len(jobs) == 1 and jobs[0].status == "RUNNING"
        history = case.owner.journal.read(session, case.request, job_id=jobs[0].job_id)
        assert len(history.launches) == ordinal and history.launches[-1].receipt is None


def test_partial_publication_and_late_authority_failure_never_reencode(owner_case):
    case = owner_case
    case.execution.revoke_after_output = True
    with pytest.raises(ValueError, match="EXPIRED_AFTER_PUBLICATION"):
        case.owner.run_launches(case.request)
    assert len(case.reader.members) == len(case.execution.calls) == 1
    case.admission.late_error = None
    with pytest.raises(ValueError, match="ORIGINAL_EXECUTION_UNRESOLVED"):
        case.owner.run_launches(case.request)
    assert len(case.execution.calls) == 1


def test_valid_failed_result_is_preserved_without_dispatching_the_next_launch(owner_case):
    case = owner_case
    case.execution.failed_result = True
    with pytest.raises(ValueError, match="PREVIOUS_NOT_COMPLETED"):
        case.owner.run_launches(case.request)
    assert len(case.execution.calls) == 1
    with case.sessions() as session, session.begin():
        job = session.scalar(select(JobRecord))
        history = case.owner.journal.read(session, case.request, job_id=job.job_id)
        assert len(history.launches) == 1 and history.launches[0].receipt is not None


@pytest.mark.parametrize("fault", ("missing", "runtime", "orphan", "source"))
def test_failed_preflight_or_current_authority_creates_no_job(owner_case, monkeypatch, fault):
    case = owner_case

    def deny(*_):
        raise ValueError("SYNTHETIC_UNAVAILABLE")

    if fault == "missing":
        case.owner.execution = None
    elif fault == "runtime":
        monkeypatch.setattr(case.execution, "assert_installed", deny)
    elif fault == "orphan":
        monkeypatch.setattr(module, "require_no_active_native_cpu_execution", deny)
    else:
        case.admission.late_error = ValueError("SYNTHETIC_UNAVAILABLE")
    with pytest.raises(ValueError):
        case.owner.run_launches(case.request)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
    assert not case.execution.calls and not case.capacity[0]


def test_resource_authorization_cannot_borrow_a_different_invocation(owner_case, monkeypatch):
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation

    from tests.unit.inference_transfer_embedding_fixtures import seal

    case, captured = owner_case, []
    original = case.execution.run_and_publish

    def capture(invocation, inputs, authorization):
        captured.append(authorization)
        return original(invocation, inputs, authorization)

    monkeypatch.setattr(case.execution, "run_and_publish", capture)
    case.execution.fail_ordinal = 1
    with pytest.raises(ValueError, match="EXECUTION_UNCERTAIN"):
        case.owner.run_launches(case.request)
    authorization = captured[0]
    invocation = case.execution.calls[0]
    authorization.assert_invocation(invocation)
    before = case.admission.entered
    body = invocation.model_dump(mode="json")
    body["execution_id"] = "f" * 32
    other = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    with pytest.raises(ValueError, match="LAUNCH_AUTHORIZATION_INVALID"):
        authorization.assert_invocation(other)
    assert case.admission.entered == before
