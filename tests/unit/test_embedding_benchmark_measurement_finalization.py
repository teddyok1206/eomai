"""Synthetic Identity/encoder/root proofs with real local Artifact/SQLite publication.

No test attests actual ADMIN authority, CUDA timing, sandbox or GPU activation.
"""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    BenchmarkColdTiming,
    BenchmarkLaunchReceipt,
    BenchmarkQueryTiming,
    BenchmarkSession,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_measurement_finalization as module
from eom_catalog_service.embedding_benchmark_cpu_reference import build_cpu_benchmark_reference
from eom_catalog_service.embedding_benchmark_measurement_finalization import (
    finalize_completed_benchmark_measurement,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import embedding_benchmark_measurement_publication as publication
from eom_orchestrator import embedding_device_benchmark_owner as owner_module
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    benchmark_launch_control_bytes,
)
from sqlalchemy import event, func, select

from tests.unit.embedding_benchmark_control_fixtures import association, completed, prepared
from tests.unit.embedding_device_benchmark_fixtures import launch_receipt
from tests.unit.embedding_device_benchmark_fixtures import session as native_session
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_numerical_assessment import reseal_launch
from tests.unit.test_embedding_benchmark_numerical_assessment import series as series
from tests.unit.test_embedding_benchmark_owner_admission import NOW
from tests.unit.test_embedding_benchmark_owner_admission import admitted as admitted

SCHEMA = EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF
CONTROL = "eom://schemas/workflow/embedding-benchmark-launch-control/1.0#/$defs/"


def publish_launch(value, root, source, invocation, *, controller_release="a" * 40):
    """Build complete synthetic canonical owner proof under preselected launch IDs."""
    numerical = reseal_launch(source, invocation=invocation)
    ordinal = invocation.launch_ordinal
    identity = ControlFileSetIdentity(
        "job_" + uuid4().hex, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
    )
    documents = {
        "worker-result.json": (embedding_device_benchmark_bytes(numerical.result), "workerResult"),
        "token-witness.json": (embedding_device_benchmark_bytes(numerical.witness), "tokenWitness"),
        "resources.json": (
            embedding_device_benchmark_bytes(numerical.result.resources),
            "resources",
        ),
    }
    # A valid synthetic transcript keeps all released checkpoint/ack hashes.
    body = native_session(ordinal).model_dump(mode="json")
    checkpoints, acks = [], []
    for checkpoint, ack in zip(body["checkpoints"], body["acks"], strict=True):
        checkpoint.update(
            execution_id=invocation.execution_id, invocation_sha256=invocation.invocation_sha256
        )
        checkpoints.append(seal(checkpoint, "checkpoint_sha256"))
        ack.update(
            execution_id=invocation.execution_id,
            invocation_sha256=invocation.invocation_sha256,
            checkpoint_sha256=checkpoints[-1]["checkpoint_sha256"],
        )
        acks.append(ack)
    body.update(
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        checkpoints=checkpoints,
        acks=acks,
    )
    transcript = BenchmarkSession.model_validate(seal(body, "session_sha256"))
    documents["session.json"] = (embedding_device_benchmark_bytes(transcript), "session")
    assoc = association(ordinal)
    before = prepared(assoc).model_dump(mode="json")
    before.update(
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        controller_release=controller_release,
    )
    before = BenchmarkLaunchPrepared.model_validate(seal(before, "prepared_sha256"))
    after = completed(assoc, prepared(assoc)).model_dump(mode="json")
    after.update(
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        prepared_sha256=before.prepared_sha256,
        resources=numerical.result.resources.model_dump(mode="json")
        if invocation.device == "CUDA"
        else None,
    )
    after = BenchmarkLaunchCompleted.model_validate(seal(after, "completion_sha256"))
    documents["root-prepared.json"] = (benchmark_launch_control_bytes(before), "prepared")
    documents["root-completion.json"] = (benchmark_launch_control_bytes(after), "completed")
    native = numerical.result.timings
    cold = BenchmarkColdTiming(
        launch_ordinal=ordinal,
        end_to_end_ns=native.startup_ns + native.load_hash_ns + native.cold_encode_ns + 1000,
        startup_ns=native.startup_ns,
        load_hash_ns=native.load_hash_ns,
        encode_ns=native.cold_encode_ns,
    )
    documents["cold-timing.json"] = (canonical_json_bytes(cold), "coldTiming")
    for query in native.query_encode_ns:
        timing = BenchmarkQueryTiming(
            **query.model_dump(mode="json"),
            authorization_ns=100,
            end_to_end_ns=query.encode_ns + 1000,
        )
        documents[f"query-timing-{query.query_ordinal}-{query.repetition}.json"] = (
            canonical_json_bytes(timing),
            "queryTiming",
        )
    binaries = dict(numerical.binaries)
    if ordinal == 1:
        unit = (1.0,) + (0.0,) * 1023
        reference, scores = build_cpu_benchmark_reference(
            invocation,
            tuple((row, unit) for row in value.request.document_rows),
            tuple((row, unit) for row in value.request.query_rows),
            artifact_id=identity.artifact_id,
            artifact_revision_id=identity.artifact_revision_id,
        )
        documents["near-tie-reference.json"] = (
            embedding_device_benchmark_bytes(reference),
            "nearTieReference",
        )
        binaries["rank-evidence.f64"] = scores

    def schema(name, definition):
        return (CONTROL if name.startswith("root-") else SCHEMA + "#/$defs/") + definition

    def pointer(name):
        raw, definition = documents[name]
        return ArtifactMemberPointer(
            artifact_id=identity.artifact_id,
            artifact_revision_id=identity.artifact_revision_id,
            member_path=name,
            schema_ref=schema(name, definition),
            media_type="application/json",
            sha256=sha256_bytes(raw),
        )

    body = launch_receipt(ordinal).model_dump(mode="json")
    body.update(
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        worker_result=pointer("worker-result.json"),
        session=pointer("session.json"),
        evidence=pointer("near-tie-reference.json" if ordinal == 1 else "root-completion.json"),
    )
    receipt = BenchmarkLaunchReceipt.model_validate(seal(body, "receipt_sha256"))
    documents["launch-receipt.json"] = (embedding_device_benchmark_bytes(receipt), "launchReceipt")
    files = []
    for name in sorted(set(documents) | set(binaries)):
        if name in documents:
            raw, definition = documents[name]
            member_schema, media = schema(name, definition), "application/json"
        else:
            raw = binaries[name]
            member_schema = (
                "eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0"
                if name.endswith(".f64")
                else "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"
            )
            media = "application/octet-stream"
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o600)
        files.append(
            ControlFileSetMember(name, path, sha256_bytes(raw), len(raw), member_schema, media)
        )
    value.publisher.publish_identified(
        identity=identity,
        members=tuple(files),
        primary_file="worker-result.json",
        artifact_type=BENCHMARK_LAUNCH_ARTIFACT_TYPE,
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key=f"synthetic-full-{ordinal}",
        source_commit=controller_release,
        created_at=NOW,
    )
    return receipt


@pytest.fixture
def measurement(admitted, series, monkeypatch, tmp_path, request):
    value = admitted
    value.publisher.settings = replace(value.publisher.settings, runtime_source_commit="a" * 40)
    engine = value.publisher.engine
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.create_function(
            "pg_try_advisory_xact_lock", 1, lambda _: True
        ),
    )
    engine.dispose()

    @contextmanager
    def capacity():
        yield

    monkeypatch.setattr(owner_module, "native_cpu_capacity", capacity)
    monkeypatch.setattr(owner_module, "require_no_active_native_cpu_execution", lambda: None)
    calls = []

    class Execution:
        def assert_installed(self, request):
            assert request == value.request

        def run_and_publish(self, invocation, inputs, authorization):
            assert inputs == value.inputs
            calls.append(invocation)
            authorization.assert_current()
            root = tmp_path / f"launch-{invocation.launch_ordinal}"
            root.mkdir()
            release = (
                "b" * 40
                if getattr(request, "param", None) == "mixed" and invocation.launch_ordinal > 1
                else "a" * 40
            )
            receipt = publish_launch(
                value,
                root,
                series[invocation.launch_ordinal - 1],
                invocation,
                controller_release=release,
            )
            authorization.assert_current()
            return receipt

    owner = BenchmarkExecutionOwner(
        value.publisher.sessions, admission=value.owner, execution=Execution()
    )
    launched = owner.run_launches(value.request)
    value.publisher.settings.staging_root.chmod(0o750)
    assert len(calls) == launched.dispatch_count == 6
    return SimpleNamespace(admitted=value, owner=owner, launched=launched, calls=calls)


def finalize(case):
    return finalize_completed_benchmark_measurement(
        case.owner, case.admitted.publisher, case.admitted.request, job_id=case.launched.job_id
    )


@pytest.mark.parametrize("measurement", ["mixed"], indirect=True)
def test_compatible_transport_repair_preserves_actual_per_launch_sources(measurement, monkeypatch):
    observations = []

    class Capture:
        def assert_unchanged(self):
            observations.append("revalidated")

    def capture(releases):
        observations.append(releases)
        return Capture()

    monkeypatch.setattr(module, "capture_equivalent_controller_measurements", capture)
    result = finalize(measurement)
    assert result.result.status == "MEASURED"
    assert observations == [("a" * 40,) + ("b" * 40,) * 5, "revalidated"]
    assert not finalize(measurement).created
    assert len(measurement.calls) == 6


@pytest.mark.parametrize("measurement", ["mixed"], indirect=True)
def test_incompatible_measurement_repair_cannot_promote_completed_series(measurement, monkeypatch):
    def reject(releases):
        raise ValueError("BENCHMARK_CONTROLLER_MEASUREMENT_CHANGED")

    monkeypatch.setattr(module, "capture_equivalent_controller_measurements", reject)
    with pytest.raises(ValueError, match="MEASUREMENT_CHANGED"):
        finalize(measurement)
    with measurement.owner.sessions() as session:
        job = session.get(JobRecord, measurement.launched.job_id)
        assert job.status == "VALIDATING_RESULT"


def test_real_local_canonical_publication_and_original_request_replay_dispatch_zero(measurement):
    case = measurement
    published = finalize(case)
    assert published.created and published.result.status == "MEASURED"
    gates = {gate.gate: gate for gate in published.gates.gates}
    assert gates["SANDBOX"].status == gates["IMAGE_TRAINER_REGRESSION"].status == "NOT_RUN"
    assert gates["SOURCE_AUTHORIZATION"].status == gates["RUNTIME"].status == "PASS"
    # Equal synthetic timings fail the fixed CUDA-superiority threshold, but the
    # comparison is still a complete truthful measurement, never a failed Job.
    assert gates["PERFORMANCE"].status == "FAIL"
    with case.owner.sessions() as session:
        job = session.get(JobRecord, published.job_id)
        assert job.status == "SUCCEEDED"
        assert published.result_member.artifact_id == job.logical_artifact_id
        assert published.result_member.artifact_revision_id == job.revision_id
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 8
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 8
    # Replay is independent of temporary staging and any installed execution adapter.
    case.owner.execution = None
    replay = finalize(case)
    assert not replay.created and replay.result == published.result
    original = case.owner.run_launches(case.admitted.request)
    assert original.job_id == published.job_id and original.dispatch_count == 0
    assert original.state == "SUCCEEDED" and len(case.calls) == 6


@pytest.mark.parametrize("phase", ("before_nas", "after_nas"))
def test_original_committing_manifest_recovery_no_redispatch(measurement, monkeypatch, phase):
    case = measurement
    original = publication.commit_file_set_artifact

    def interrupt(staged, root):
        if phase == "after_nas":
            original(staged, root)
        raise OSError("SYNTHETIC_COMMIT_INTERRUPTED")

    monkeypatch.setattr(publication, "commit_file_set_artifact", interrupt)
    with pytest.raises(OSError, match="SYNTHETIC_COMMIT_INTERRUPTED"):
        finalize(case)
    with case.owner.sessions() as session:
        job = session.get(JobRecord, case.launched.job_id)
        identity = (job.logical_artifact_id, job.revision_id)
        assert job.status == "COMMITTING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == job.job_id,
                    JobEventRecord.event == "BENCHMARK_MEASUREMENT_COMMITTING",
                )
            )
            == 1
        )
    case.owner.execution = None
    assert case.owner.run_launches(case.admitted.request).dispatch_count == 0
    monkeypatch.setattr(publication, "commit_file_set_artifact", original)
    # Recovery must use sealed exact bytes, not recalculate or encode.
    monkeypatch.setattr(module, "_collect_measurement", lambda *_a, **_k: pytest.fail("recomputed"))
    resumed = finalize(case)
    assert (
        resumed.created
        and (resumed.result_member.artifact_id, resumed.result_member.artifact_revision_id)
        == identity
    )
    assert not finalize(case).created and len(case.calls) == 6


def test_precommit_recovery_missing_original_f32_never_records_success(measurement, monkeypatch):
    case = measurement
    original = publication.commit_file_set_artifact
    monkeypatch.setattr(
        publication,
        "commit_file_set_artifact",
        lambda *_a: (_ for _ in ()).throw(OSError("SYNTHETIC_BEFORE_COMMIT")),
    )
    with pytest.raises(OSError, match="SYNTHETIC_BEFORE_COMMIT"):
        finalize(case)
    with case.owner.sessions() as session:
        job = session.get(JobRecord, case.launched.job_id)
        identity = (job.logical_artifact_id, job.revision_id)
        assert job.status == "COMMITTING"
        pointer = case.launched.receipts[1].worker_result
        launch = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        (Path(launch.nas_path) / "supplementary-documents.f32").unlink()
    monkeypatch.setattr(publication, "commit_file_set_artifact", original)
    monkeypatch.setattr(module, "_collect_measurement", lambda *_a, **_k: pytest.fail("recomputed"))
    monkeypatch.setattr(
        module, "assess_benchmark_series_numerics", lambda *_a, **_k: pytest.fail("reassessed")
    )
    case.owner.execution = None
    with pytest.raises((ValueError, OSError)):
        finalize(case)
    with case.owner.sessions() as session:
        assert session.get(JobRecord, case.launched.job_id).status == "COMMITTING"
        assert session.get(ArtifactRecord, identity[0]) is None
        assert session.get(ArtifactRevisionRecord, identity[1]) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == case.launched.job_id,
                    JobEventRecord.event == "BENCHMARK_MEASUREMENT_COMMITTED",
                )
            )
            == 0
        )
    assert len(case.calls) == 6


def test_precommit_required_validator_uses_success_caller_root(measurement, monkeypatch):
    case = measurement
    calls = []

    def refuse(self, session, request, *, job_id, value):
        assert self.owner is case.owner and request == case.admitted.request
        assert session.in_transaction() and not session.in_nested_transaction()
        job = session.get(JobRecord, job_id)
        assert job.status == "COMMITTING" and value.result.status == "MEASURED"
        assert session.get(ArtifactRecord, job.logical_artifact_id) is None
        assert session.get(ArtifactRevisionRecord, job.revision_id) is None
        calls.append(job_id)
        raise ValueError("SYNTHETIC_SOURCE_VALIDATOR_REFUSED")

    monkeypatch.setattr(
        module._CatalogBenchmarkMeasurementSourceValidator, "validate_in_session", refuse
    )
    with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_VALIDATOR_REFUSED"):
        finalize(case)
    with case.owner.sessions() as session:
        job = session.get(JobRecord, case.launched.job_id)
        assert job.status == "COMMITTING"
        assert session.get(ArtifactRecord, job.logical_artifact_id) is None
        assert session.get(ArtifactRevisionRecord, job.revision_id) is None
    assert calls == [case.launched.job_id] and len(case.calls) == 6


def test_corrupt_sealed_committing_intent_is_not_recomputed_or_overwritten(
    measurement, monkeypatch
):
    case = measurement
    monkeypatch.setattr(
        publication,
        "commit_file_set_artifact",
        lambda *_a: (_ for _ in ()).throw(OSError("SYNTHETIC_BEFORE_COMMIT")),
    )
    with pytest.raises(OSError, match="SYNTHETIC_BEFORE_COMMIT"):
        finalize(case)
    stage = (
        case.admitted.publisher.settings.staging_root
        / case.launched.job_id
        / "benchmark-measurement"
    )
    original = (stage / "result.json").read_bytes()
    (stage / "result.json").write_bytes(original + b" ")
    monkeypatch.setattr(module, "_collect_measurement", lambda *_a, **_k: pytest.fail("recomputed"))
    with pytest.raises(ValueError):
        finalize(case)
    with case.owner.sessions() as session:
        assert session.get(JobRecord, case.launched.job_id).status == "COMMITTING"
    assert len(case.calls) == 6


@pytest.mark.parametrize("fault", ("manifest", "size", "hash", "missing", "role", "external"))
def test_replay_rejects_revocation_dangling_and_corruption(measurement, fault):
    case = measurement
    result = finalize(case)
    with case.owner.sessions() as session, session.begin():
        revision = session.get(ArtifactRevisionRecord, result.result_member.artifact_revision_id)
        if fault == "manifest":
            revision.manifest = dict(revision.manifest) | {"untrusted_extra": True}
        elif fault == "size":
            revision.content_bytes += 1
        elif fault in {"hash", "missing"}:
            path = Path(revision.nas_path) / "cpu-documents.json"
            if fault == "missing":
                path.unlink()
            else:
                path.write_bytes(b"{}")
        elif fault == "external":
            pointer = case.launched.receipts[1].worker_result
            launch = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
            (Path(launch.nas_path) / "supplementary-documents.f32").unlink()
    if fault == "role":
        case.admitted.roles[:] = []
    with pytest.raises((ValueError, OSError)):
        finalize(case)
    assert len(case.calls) == 6


def test_no_untrusted_owner_or_other_database_can_finalize():
    with pytest.raises(ValueError, match="OWNER_INVALID"):
        finalize_completed_benchmark_measurement(
            object(), object(), object(), job_id="job_" + "a" * 32
        )


def test_bounded_member_reader_keeps_standard_nas_modes_and_stable_missing_error(tmp_path):
    path = tmp_path / "member.json"
    path.write_bytes(b"{}")
    path.chmod(0o664)  # Existing Artifact copy mode, not an authority grant.
    assert publication._read_member(path, maximum=2) == b"{}"
    with pytest.raises(ValueError, match="PUBLICATION_INVALID"):
        publication._read_member(path, maximum=1)
    path.unlink()
    with pytest.raises(ValueError, match="MEMBER_UNAVAILABLE"):
        publication._read_member(path, maximum=2)
    path.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError, match="MEMBER_UNAVAILABLE"):
        publication._read_member(path, maximum=2)


def test_publication_lock_rejects_relative_root_and_same_job_concurrent_writer(tmp_path):
    from eom_orchestrator.settings import Settings

    job_id = "job_" + "a" * 32
    with (
        pytest.raises(ValueError, match="PUBLICATION_INVALID"),
        publication._measurement_lock(Settings(staging_root=Path("relative")), job_id),
    ):
        pytest.fail("relative staging admitted")
    root = tmp_path / "staging"
    root.mkdir(mode=0o750)
    settings = Settings(staging_root=root)
    with (
        publication._measurement_lock(settings, job_id),
        pytest.raises(ValueError, match="PUBLICATION_BUSY"),
        publication._measurement_lock(settings, job_id),
    ):
        pytest.fail("concurrent same-Job writer admitted")


@pytest.mark.parametrize("reserved,process,expected", ((5, 5, False), (9, 5, True), (5, 9, True)))
def test_capacity_caps_each_gpu_observation_without_double_count(reserved, process, expected):
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerResult
    from eom_orchestrator.embedding_benchmark_launch_history import CompletedBenchmarkLaunch

    from tests.unit.embedding_device_benchmark_fixtures import (
        owner_request,
        staged_inputs,
        worker_invocation,
        worker_result,
    )

    launches = []
    for ordinal in range(1, 7):
        invocation = worker_invocation(ordinal)
        body = worker_result(ordinal).model_dump(mode="json")
        if invocation.device == "CUDA":
            resource = body["resources"]
            resource.update(
                peak_reserved_gpu_bytes=reserved * 1024**3,
                peak_whole_process_gpu_bytes=process * 1024**3,
            )
            for sample in resource["capacity_samples"]:
                sample.update(
                    peak_reserved_gpu_bytes=reserved * 1024**3,
                    peak_whole_process_gpu_bytes=process * 1024**3,
                )
            body["resources"] = seal(resource, "resource_sha256")
        result = BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))
        launches.append(CompletedBenchmarkLaunch(invocation, launch_receipt(ordinal), result))
    reasons = module._capacity_reasons(owner_request(), staged_inputs(), tuple(launches))
    assert ("GPU_LIMIT_EXCEEDED" in reasons) is expected
    assert not set(reasons) - {"GPU_LIMIT_EXCEEDED"}
