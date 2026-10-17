"""Marker-guarded PostgreSQL Job concurrency; synthetic source admission, no live model."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkOwnerRequest
from eom_catalog_service.embedding_benchmark_owner_admission import (
    BenchmarkOwnerConfiguration,
    CatalogBenchmarkOwnerAdmission,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id, sha256_bytes
from eom_identity_service import AuthenticatedSessionFence
from eom_identity_service.models import OperatorRecord
from eom_orchestrator import embedding_device_benchmark_owner as owner_module
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkJobAdmissionError,
    benchmark_job_key,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import BenchmarkLaunchJournal
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_authenticated_session_fence import (
    owner_engine as owner_engine,
)
from tests.integration.test_authenticated_session_fence import (
    prepared as prepared,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import (
    SyntheticResultReader,
    invocation_for,
    receipt_for,
)
from tests.unit.test_embedding_device_benchmark_owner import (
    SyntheticExecution,
    SyntheticOwnerAdmission,
)


def _launch_storage(engine):
    request, inputs = benchmark_case()
    admission, reader = SyntheticBenchmarkAdmission(request, inputs), SyntheticResultReader()
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    return sessions, admission, reader, BenchmarkLaunchJournal(admission, reader), job_id


pytestmark = pytest.mark.integration


def test_postgres_identified_cpu_reference_publication_has_one_timestamp_and_allocation(
    guarded_engine, tmp_path
):
    """Actual PG/file-set commit and replay; CPU vectors/source grant remain synthetic."""
    from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes

    from tests.unit.embedding_device_benchmark_fixtures import worker_result
    from tests.unit.test_embedding_benchmark_cpu_reference import cpu_reference

    nas = tmp_path / "nas"
    nas.mkdir()
    publisher = ControlFileSetPublisher(
        guarded_engine, Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas)
    )
    identity = ControlFileSetIdentity(new_job_id(), new_logical_artifact_id(), new_revision_id())
    reference, pointer, raw, scores = cpu_reference(
        artifact_id=identity.artifact_id, artifact_revision_id=identity.artifact_revision_id
    )
    members = []
    for name, payload, schema, media in (
        (
            "worker-result.json",
            embedding_device_benchmark_bytes(worker_result()),
            "eom://schemas/knowledge/embedding-device-benchmark/1.0#/$defs/workerResult",
            "application/json",
        ),
        ("near-tie-reference.json", raw, pointer.schema_ref, "application/json"),
        (
            "rank-evidence.f64",
            scores,
            reference.score_binary.schema_ref,
            "application/octet-stream",
        ),
    ):
        path = tmp_path / name
        path.write_bytes(payload)
        path.chmod(0o600)
        members.append(
            ControlFileSetMember(name, path, sha256_bytes(payload), len(payload), schema, media)
        )
    key = "synthetic-cpu-reference:" + identity.job_id
    arguments = dict(
        identity=identity,
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file="worker-result.json",
        artifact_type="control_embedding_benchmark_launch",
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key=key,
        source_commit="a" * 40,
    )
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=5)
        try:
            return publisher.publish_identified_first_observation(**arguments)
        except ControlPlaneError as error:
            assert error.code == "CONTROL_FILE_SET_BUSY"
            return None

    before = datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: publish(), range(2)))
    assert any(result is not None for result in results)
    first = publisher.publish_identified_first_observation(**arguments)
    after = datetime.now(UTC)
    assert all(result is None or result == first for result in results)
    assert (first.job_id, first.artifact_id, first.artifact_revision_id) == (
        identity.job_id,
        identity.artifact_id,
        identity.artifact_revision_id,
    )
    with Session(guarded_engine) as session:
        job = session.get(JobRecord, identity.job_id)
        assert (
            before
            <= datetime.fromisoformat(job.request["created_at_utc"].replace("Z", "+00:00"))
            <= after
        )
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == identity.job_id)
            )
            == 1
        )
    assert publisher.publish_identified_first_observation(**arguments) == first


def test_postgres_same_identity_replay_has_one_original_job_and_two_events(guarded_engine: Engine):
    request, inputs = benchmark_case()
    admission = SyntheticBenchmarkAdmission(request, inputs)
    identities = []
    for created in (True, False):
        with Session(guarded_engine) as session, session.begin():
            job, observed = submit_benchmark_job_in_session(
                session, request, source_admission=admission
            )
            assert observed is created and job.status == "VALIDATED"
            identities.append((job.job_id, job.logical_artifact_id, job.revision_id))
    assert identities[0] == identities[1] and admission.entered == admission.exited == 2
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == identities[0][0])
            )
            == 2
        )
        assert session.get(ArtifactRecord, identities[0][1]) is None


def test_postgres_parallel_submission_is_busy_until_original_commit_then_replays(
    guarded_engine: Engine,
):
    request, inputs = benchmark_case()
    ready, finish = Event(), Event()

    def first():
        admission = SyntheticBenchmarkAdmission(request, inputs)
        with Session(guarded_engine) as session, session.begin():
            job, created = submit_benchmark_job_in_session(
                session, request, source_admission=admission
            )
            assert created
            identifier = job.job_id
            ready.set()
            assert finish.wait(10)
        return identifier

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first)
        try:
            assert ready.wait(10)
            with (
                pytest.raises(BenchmarkJobAdmissionError, match="SUBMISSION_BUSY"),
                Session(guarded_engine) as session,
                session.begin(),
            ):
                submit_benchmark_job_in_session(
                    session, request, source_admission=SyntheticBenchmarkAdmission(request, inputs)
                )
        finally:
            finish.set()
        identifier = future.result(timeout=15)
    with Session(guarded_engine) as session, session.begin():
        job, created = submit_benchmark_job_in_session(
            session, request, source_admission=SyntheticBenchmarkAdmission(request, inputs)
        )
        assert not created and job.job_id == identifier
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == identifier)
            )
            == 2
        )


def test_postgres_late_authority_failure_rolls_back_job_and_releases_submission_lock(
    guarded_engine: Engine,
):
    request, inputs = benchmark_case()
    admission = SyntheticBenchmarkAdmission(request, inputs)
    admission.late_error = ValueError("SYNTHETIC_EXPIRED")
    with (
        pytest.raises(ValueError, match="EXPIRED"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        submit_benchmark_job_in_session(session, request, source_admission=admission)
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            is None
        )
    with Session(guarded_engine) as session, session.begin():
        job, created = submit_benchmark_job_in_session(
            session, request, source_admission=SyntheticBenchmarkAdmission(request, inputs)
        )
        assert created and job.status == "VALIDATED"


def test_postgres_failed_original_remains_failed_and_changed_identity_payload_conflicts(
    guarded_engine: Engine,
):
    request, inputs = benchmark_case()
    admission = SyntheticBenchmarkAdmission(request, inputs)
    with Session(guarded_engine) as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        identifier = job.job_id
        transition_job(session, identifier, JobState.FAILED, "SYNTHETIC_BENCHMARK_FAILURE")
    body = request.model_dump(mode="json")
    body["policy_sha256"] = "sha256:" + "0" * 64
    other = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    with (
        pytest.raises(BenchmarkJobAdmissionError, match="HISTORY_CONFLICT"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        submit_benchmark_job_in_session(
            session, other, source_admission=SyntheticBenchmarkAdmission(other, inputs)
        )
    with Session(guarded_engine) as session, session.begin():
        job, created = submit_benchmark_job_in_session(session, request, source_admission=admission)
        assert not created and job.job_id == identifier and job.status == "FAILED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == identifier)
            )
            == 3
        )


def test_postgres_concurrent_launch_reservation_and_receipt_are_exact_replays(
    guarded_engine: Engine,
):
    sessions, admission, reader, journal, job_id = storage = _launch_storage(guarded_engine)
    invocation = invocation_for(storage, 1)
    receipt = receipt_for(storage, invocation)

    def submit(value, operation):
        with sessions() as session, session.begin():
            return getattr(journal, operation)(session, admission.request, value)[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        for value, operation in ((invocation, "reserve"), (receipt, "record")):
            futures = [executor.submit(submit, value, operation) for _ in range(2)]
            assert sorted(future.result(timeout=15) for future in futures) == [False, True]
    with sessions() as session, session.begin():
        history = journal.read(session, admission.request, job_id=job_id)
        assert len(history.launches) == 1 and history.launches[0].receipt == receipt
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
            )
            == 7
        )
    assert len(reader.reads) == 1


def test_postgres_six_launches_remain_one_job_and_late_failure_rolls_back(guarded_engine: Engine):
    sessions, admission, _, journal, job_id = storage = _launch_storage(guarded_engine)
    for ordinal in range(1, 7):
        invocation = invocation_for(storage, ordinal)
        with sessions() as session, session.begin():
            _, created = journal.reserve(session, admission.request, invocation)
            assert created
        receipt = receipt_for(storage, invocation)
        admission.late_error = ValueError("SYNTHETIC_LATE_REVOKED")
        with (
            pytest.raises(ValueError, match="LATE_REVOKED"),
            sessions() as session,
            session.begin(),
        ):
            journal.record(session, admission.request, receipt)
        admission.late_error = None
        with sessions() as session, session.begin():
            history = journal.read(session, admission.request, job_id=job_id)
            assert history.launches[-1].receipt is None
            _, created = journal.record(session, admission.request, receipt)
            assert created
    with sessions() as session, session.begin():
        history = journal.read(session, admission.request, job_id=job_id)
        assert len(history.launches) == 6 and history.job_state == "RUNNING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
            )
            == 17
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRecord)
                .where(ArtifactRecord.job_id == job_id)
            )
            == 0
        )


def _manual_owner_case(engine, monkeypatch):
    request, inputs = benchmark_case()
    reader = SyntheticResultReader()
    admission = SyntheticOwnerAdmission(request, inputs, reader)
    state = SimpleNamespace(
        request=request,
        inputs=inputs,
        admission=admission,
        reader=reader,
        sessions=sessionmaker(engine, expire_on_commit=False),
        capacity=[False],
    )

    @contextmanager
    def synthetic_capacity():
        state.capacity[0] = True
        try:
            yield
        finally:
            state.capacity[0] = False

    monkeypatch.setattr(owner_module, "native_cpu_capacity", synthetic_capacity)
    monkeypatch.setattr(owner_module, "require_no_active_native_cpu_execution", lambda: None)
    state.execution = SyntheticExecution(state)
    state.owner = BenchmarkExecutionOwner(
        state.sessions, admission=admission, execution=state.execution
    )
    state.storage = (state.sessions, admission, reader, state.owner.journal, None)
    return state


def test_postgres_manual_owner_series_commits_short_roots_and_replays_no_dispatch(
    guarded_engine: Engine,
    monkeypatch,
):
    state = _manual_owner_case(guarded_engine, monkeypatch)
    result = state.owner.run_launches(state.request)
    assert result.dispatch_count == 6 and result.state == "VALIDATING_RESULT"
    assert len({value.execution_id for value in state.execution.calls}) == 6
    state.owner.execution = None
    replay = state.owner.run_launches(state.request)
    assert replay.receipts == result.receipts and replay.dispatch_count == 0
    with state.sessions() as session:
        assert session.get(JobRecord, result.job_id).status == "VALIDATING_RESULT"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == result.job_id)
            )
            == 18
        )


def test_postgres_manual_owner_does_not_replace_an_uncertain_original_execution(
    guarded_engine: Engine,
    monkeypatch,
):
    state = _manual_owner_case(guarded_engine, monkeypatch)
    state.execution.fail_ordinal = 2
    with pytest.raises(ValueError, match="EXECUTION_UNCERTAIN"):
        state.owner.run_launches(state.request)
    before = tuple(state.execution.calls)
    state.execution.fail_ordinal = None
    with pytest.raises(ValueError, match="ORIGINAL_EXECUTION_UNRESOLVED"):
        state.owner.run_launches(state.request)
    assert tuple(state.execution.calls) == before and len(before) == 2
    with state.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == benchmark_job_key(state.request))
            )
            == 1
        )


@pytest.mark.api_integration
@pytest.mark.parametrize("actor", ("admin", "author"))
def test_real_identity_capture_and_registered_policy_gate_the_manual_benchmark(
    prepared,
    tmp_path,
    actor,
):
    """Real disposable Identity/Artifact fences; source port is explicitly synthetic."""
    capture = prepared.capture
    if actor == "admin":
        with Session(prepared.engine) as session:
            username = session.get(OperatorRecord, prepared.admin.operator_id).username
        pair = prepared.auth.login(
            username=username, password=prepared.password, client_name="Synthetic benchmark gate"
        ).pair
        capture = prepared.auth.capture_access(pair.access_token)
    request, inputs = benchmark_case()
    body = request.model_dump(mode="json")
    body["operator_audit_id"] = capture.operator_id
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    workspace, artifacts = tmp_path / "workspace", tmp_path / "artifacts"
    workspace.mkdir(mode=0o700)
    artifacts.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        prepared.engine, Settings(workspace_root=workspace, nas_artifact_root=artifacts)
    )
    published = LocalEmbeddingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ).publish_benchmark_policy(
        request.execution_policy,
        idempotency_key="synthetic-native-policy:" + request.benchmark_id,
        created_at=datetime.now(UTC),
    )
    owner = CatalogBenchmarkOwnerAdmission(
        prepared.engine,
        BenchmarkOwnerConfiguration(
            request.request_sha256, published.member, published.semantic_sha256
        ),
        capture=capture,
        session_fence=AuthenticatedSessionFence(prepared.pin),
        settings=CatalogSettings(nas_artifact_root=artifacts),
    )
    synthetic_source = SyntheticBenchmarkAdmission(request, inputs)
    owner._source = synthetic_source
    if actor == "admin":
        with (
            Session(prepared.engine) as session,
            session.begin(),
            owner.admit_execution_in_session(session, request) as admitted,
        ):
            assert admitted == inputs
        assert synthetic_source.entered == synthetic_source.exited == 1
    else:
        with (
            pytest.raises(ValueError),
            Session(prepared.engine) as session,
            session.begin(),
            owner.admit_execution_in_session(session, request),
        ):
            pytest.fail("an AUTHOR capture cannot authorize benchmark compute")
        assert synthetic_source.entered == 0
