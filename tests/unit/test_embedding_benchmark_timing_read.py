"""Actual local Artifact timing reads; declared Identity/Graph fixtures are synthetic."""

from dataclasses import replace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    BenchmarkColdTiming,
    BenchmarkLaunchReceipt,
    BenchmarkQueryTiming,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service.embedding_benchmark_timing_read import (
    read_completed_benchmark_series_timings,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.embedding_benchmark_launch_history import CompletedBenchmarkLaunch
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord

from tests.unit.embedding_device_benchmark_fixtures import (
    launch_receipt,
    worker_invocation,
    worker_result,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_owner_admission import NOW
from tests.unit.test_embedding_benchmark_owner_admission import admitted as admitted


def published_launch(value, tmp_path, ordinal, *, selected_invocation=None):
    body = worker_invocation(ordinal).model_dump(mode="json")
    raw_inputs = embedding_device_benchmark_bytes(value.inputs)
    body.update(
        benchmark_id=value.request.benchmark_id,
        benchmark_revision_id=value.request.benchmark_revision_id,
        owner_request_sha256=value.request.request_sha256,
        local_input=dict(
            member_name="benchmark-inputs.json",
            sha256=sha256_bytes(raw_inputs),
            byte_count=len(raw_inputs),
        ),
    )
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    if selected_invocation is not None:
        invocation = selected_invocation
    body = worker_result(ordinal).model_dump(mode="json")
    body.update(
        invocation_sha256=invocation.invocation_sha256, execution_id=invocation.execution_id
    )
    for field, hash_name in (("timings", "timing_sha256"), ("resources", "resource_sha256")):
        body[field] = seal(
            body[field] | {"invocation_sha256": invocation.invocation_sha256}, hash_name
        )
    result = BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))
    native = result.timings
    cold = BenchmarkColdTiming(
        launch_ordinal=ordinal,
        end_to_end_ns=native.startup_ns + native.load_hash_ns + native.cold_encode_ns + 1000,
        startup_ns=native.startup_ns,
        load_hash_ns=native.load_hash_ns,
        encode_ns=native.cold_encode_ns,
    )
    documents = {
        "worker-result.json": ("workerResult", embedding_device_benchmark_bytes(result)),
        "cold-timing.json": ("coldTiming", canonical_json_bytes(cold)),
    }
    queries = tuple(
        BenchmarkQueryTiming(
            **q.model_dump(mode="json"), authorization_ns=100, end_to_end_ns=q.encode_ns + 1000
        )
        for q in native.query_encode_ns
    )
    documents.update(
        {
            f"query-timing-{q.query_ordinal}-{q.repetition}.json": (
                "queryTiming",
                canonical_json_bytes(q),
            )
            for q in queries
        }
    )
    files = []
    for name, (definition, raw) in sorted(documents.items()):
        path = tmp_path / name
        path.write_bytes(raw)
        path.chmod(0o600)
        files.append(
            ControlFileSetMember(
                name,
                path,
                sha256_bytes(raw),
                len(raw),
                EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/" + definition,
                "application/json",
            )
        )
    published = value.publisher.publish(
        members=tuple(files),
        primary_file="worker-result.json",
        artifact_type=BENCHMARK_LAUNCH_ARTIFACT_TYPE,
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        # Reusing the disposable DB must not alias independent original launches.
        idempotency_key=f"synthetic-timing-{invocation.execution_id}-{ordinal}",
        source_commit="a" * 40,
        created_at=NOW,
    )
    receipt_body = launch_receipt(ordinal).model_dump(mode="json")
    receipt_body.update(
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
    )
    for field in ("worker_result", "session", "evidence"):
        receipt_body[field].update(
            artifact_id=published.artifact_id, artifact_revision_id=published.artifact_revision_id
        )
    receipt_body["worker_result"]["sha256"] = sha256_bytes(documents["worker-result.json"][1])
    receipt = BenchmarkLaunchReceipt.model_validate(seal(receipt_body, "receipt_sha256"))
    return CompletedBenchmarkLaunch(invocation, receipt, result), cold, queries, published


@pytest.mark.parametrize("ordinal", [1, 3])
def test_registered_original_timing_bytes_are_read_without_new_job_or_result_parse(
    admitted, tmp_path, ordinal
):
    launch, cold, queries, _published = published_launch(admitted, tmp_path, ordinal)
    with admitted.publisher.sessions() as session, session.begin():
        result = admitted.owner.read_launch_timings_in_session(session, admitted.request, launch)
        assert result.invocation == launch.invocation and result.native is launch.result.timings
        assert result.cold == cold and result.queries == queries
    assert admitted.owner._source.entered == admitted.owner._source.exited == 1


@pytest.mark.parametrize(
    "fault", ["corrupt", "descriptor", "producer", "role", "late_role", "foreign_result"]
)
def test_corrupt_member_current_revocation_or_foreign_result_is_not_a_performance_sample(
    admitted, tmp_path, monkeypatch, fault
):
    launch, _cold, _queries, published = published_launch(admitted, tmp_path, 1)
    if fault in {"corrupt", "descriptor", "producer"}:
        with admitted.publisher.sessions() as session, session.begin():
            revision = session.get(ArtifactRevisionRecord, published.artifact_revision_id)
            if fault == "producer":
                session.get(JobRecord, published.job_id).status = "FAILED"
            elif fault == "descriptor":
                from copy import deepcopy

                manifest = deepcopy(revision.manifest)
                for member in manifest["files"]:
                    if member["file_name"] == "cold-timing.json":
                        member["schema_ref"] = "eom://schemas/other/1.0"
                revision.manifest = manifest
            else:
                from pathlib import Path

                location = Path(revision.nas_path) / "cold-timing.json"
                location.write_bytes(b"{}")
    elif fault == "role":
        admitted.roles[:] = []
    elif fault == "late_role":
        from eom_catalog_service import embedding_benchmark_owner_admission as module

        original = module.PinnedArtifactReadContext.revalidate_provenance

        def revoke(reader):
            original(reader)
            admitted.roles[:] = []

        monkeypatch.setattr(module.PinnedArtifactReadContext, "revalidate_provenance", revoke)
    else:
        launch = replace(launch, result=worker_result(1))
    with pytest.raises(ValueError), admitted.publisher.sessions() as session, session.begin():
        admitted.owner.read_launch_timings_in_session(session, admitted.request, launch)


def test_audit_data_or_untrusted_owner_does_not_open_a_series_reader():
    with pytest.raises(ValueError, match="BENCHMARK_TIMING_READER_OWNER_INVALID"):
        read_completed_benchmark_series_timings(object(), object(), job_id="job_" + "a" * 32)


def test_original_journal_to_registered_six_launch_timing_assessment_is_read_only(
    admitted, tmp_path, monkeypatch
):
    from contextlib import contextmanager

    from eom_orchestrator import embedding_device_benchmark_owner as owner_module
    from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
    from sqlalchemy import event, func, select

    engine = admitted.publisher.engine
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.create_function(
            "pg_try_advisory_xact_lock", 1, lambda _: True
        ),
    )
    engine.dispose()

    @contextmanager
    def synthetic_capacity():
        yield

    monkeypatch.setattr(owner_module, "native_cpu_capacity", synthetic_capacity)
    monkeypatch.setattr(owner_module, "require_no_active_native_cpu_execution", lambda: None)
    dispatched = []

    class SyntheticExecution:
        def assert_installed(self, request):
            assert request == admitted.request

        def run_and_publish(self, invocation, inputs, authorization):
            authorization.assert_invocation(invocation)
            dispatched.append(invocation)
            launch, *_ = published_launch(
                admitted, tmp_path, invocation.launch_ordinal, selected_invocation=invocation
            )
            authorization.assert_invocation(invocation)
            return launch.receipt

    owner = BenchmarkExecutionOwner(
        admitted.publisher.sessions, admission=admitted.owner, execution=SyntheticExecution()
    )
    series = owner.run_launches(admitted.request)
    assert len(dispatched) == 6 and series.state == "VALIDATING_RESULT"
    owner.execution = None
    with owner.sessions() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    first = read_completed_benchmark_series_timings(owner, admitted.request, job_id=series.job_id)
    second = read_completed_benchmark_series_timings(owner, admitted.request, job_id=series.job_id)
    assert first == second and first.performance.verdict == "KEEP_CPU"
    assert tuple(c.launch_ordinal for c in first.cpu.cold) == (1, 4, 5)
    assert tuple(c.launch_ordinal for c in first.cuda.cold) == (2, 3, 6)
    with owner.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
        assert session.get(JobRecord, series.job_id).status == "VALIDATING_RESULT"
    assert len(dispatched) == 6
    admitted.roles[:] = []
    with pytest.raises(ValueError, match="ADMIN_REQUIRED"):
        read_completed_benchmark_series_timings(owner, admitted.request, job_id=series.job_id)
