"""Real local registered f32/witness reads; synthetic encoding/Identity/Graph, not live proof."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    BenchmarkLaunchReceipt,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_owner_admission as admission_module
from eom_catalog_service.embedding_benchmark_cpu_reference import build_cpu_benchmark_reference
from eom_catalog_service.embedding_benchmark_numerical_read import (
    read_completed_benchmark_series_numerics,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator import embedding_device_benchmark_owner as owner_module
from eom_orchestrator.embedding_benchmark_launch_history import CompletedBenchmarkLaunch
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy import event, func, select

from tests.unit.embedding_device_benchmark_fixtures import launch_receipt
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_numerical_assessment import reseal_launch
from tests.unit.test_embedding_benchmark_numerical_assessment import series as series
from tests.unit.test_embedding_benchmark_owner_admission import NOW
from tests.unit.test_embedding_benchmark_owner_admission import admitted as admitted


def published_numerical_launch(admitted, root, source, *, invocation=None):
    if invocation is None:
        body = source.invocation.model_dump(mode="json")
        raw_inputs = embedding_device_benchmark_bytes(admitted.inputs)
        body.update(
            benchmark_id=admitted.request.benchmark_id,
            benchmark_revision_id=admitted.request.benchmark_revision_id,
            owner_request_sha256=admitted.request.request_sha256,
            local_input=dict(
                member_name="benchmark-inputs.json",
                sha256=sha256_bytes(raw_inputs),
                byte_count=len(raw_inputs),
            ),
        )
        invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    numerical = reseal_launch(source, invocation=invocation)
    identity = ControlFileSetIdentity(
        "job_" + uuid4().hex, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
    )
    schema = EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF
    documents = {
        "worker-result.json": (
            embedding_device_benchmark_bytes(numerical.result),
            schema + "#/$defs/workerResult",
            "application/json",
        ),
        "token-witness.json": (
            embedding_device_benchmark_bytes(numerical.witness),
            schema + "#/$defs/tokenWitness",
            "application/json",
        ),
    } | {
        name: (
            raw,
            "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
            "application/octet-stream",
        )
        for name, raw in numerical.binaries
    }
    if invocation.launch_ordinal == 1:
        unit = (1.0,) + (0.0,) * 1023
        reference, scores = build_cpu_benchmark_reference(
            invocation,
            tuple((row, unit) for row in admitted.request.document_rows),
            tuple((row, unit) for row in admitted.request.query_rows),
            artifact_id=identity.artifact_id,
            artifact_revision_id=identity.artifact_revision_id,
        )
        documents["near-tie-reference.json"] = (
            embedding_device_benchmark_bytes(reference),
            schema + "#/$defs/nearTieReference",
            "application/json",
        )
        documents["rank-evidence.f64"] = (
            scores,
            reference.score_binary.schema_ref,
            "application/octet-stream",
        )
    files = []
    for name, (raw, member_schema, media) in sorted(documents.items()):
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o600)
        files.append(
            ControlFileSetMember(name, path, sha256_bytes(raw), len(raw), member_schema, media)
        )
    published = admitted.publisher.publish_identified(
        identity=identity,
        members=tuple(files),
        primary_file="worker-result.json",
        artifact_type=BENCHMARK_LAUNCH_ARTIFACT_TYPE,
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key=f"synthetic-numerical-{invocation.launch_ordinal}",
        source_commit="a" * 40,
        created_at=NOW,
    )
    body = launch_receipt(invocation.launch_ordinal).model_dump(mode="json")
    body.update(
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
    )
    for field in ("worker_result", "session", "evidence"):
        body[field].update(
            artifact_id=published.artifact_id, artifact_revision_id=published.artifact_revision_id
        )
    body["worker_result"]["sha256"] = sha256_bytes(documents["worker-result.json"][0])
    if invocation.launch_ordinal == 1:
        body["evidence"].update(
            member_path="near-tie-reference.json",
            schema_ref=schema + "#/$defs/nearTieReference",
            sha256=sha256_bytes(documents["near-tie-reference.json"][0]),
        )
    receipt = BenchmarkLaunchReceipt.model_validate(seal(body, "receipt_sha256"))
    return CompletedBenchmarkLaunch(invocation, receipt, numerical.result), numerical, published


@pytest.mark.parametrize("ordinal", (1, 3))
def test_original_registered_token_and_unique_f32_members_materialize_once(
    admitted, tmp_path, monkeypatch, series, ordinal
):
    launch, expected, _ = published_numerical_launch(admitted, tmp_path, series[ordinal - 1])
    calls = Counter()
    original = admission_module.PinnedArtifactReadContext.read_pinned

    def read(reader, **kwargs):
        calls[kwargs["member_path"]] += 1
        return original(reader, **kwargs)

    monkeypatch.setattr(admission_module.PinnedArtifactReadContext, "read_pinned", read)
    with admitted.publisher.sessions() as session, session.begin():
        value = admitted.owner.read_launch_numerics_in_session(session, admitted.request, launch)
    assert value == expected and value.result is launch.result
    assert calls["token-witness.json"] == 1 and calls["worker-result.json"] == 0
    assert {name: calls[name] for name, _ in expected.binaries} == {
        name: 1 for name, _ in expected.binaries
    }
    if ordinal == 1:
        assert len(embedding_device_benchmark_bytes(value.witness)) > 64 * 1024
    assert admitted.owner._source.entered == admitted.owner._source.exited == 1


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "corrupt",
        "descriptor",
        "producer",
        "approval",
        "role",
        "late_role",
        "foreign_result",
        "schema_error",
    ),
)
def test_missing_corrupt_revoked_or_foreign_members_do_not_become_numerical_evidence(
    admitted, tmp_path, monkeypatch, series, fault
):
    launch, _expected, published = published_numerical_launch(admitted, tmp_path, series[0])
    if fault in {"missing", "corrupt", "descriptor", "producer", "approval"}:
        with admitted.publisher.sessions() as session, session.begin():
            revision = session.get(ArtifactRevisionRecord, published.artifact_revision_id)
            if fault == "producer":
                session.get(JobRecord, published.job_id).status = "FAILED"
            elif fault == "approval":
                session.get(ArtifactRecord, published.artifact_id).approved = False
            elif fault == "descriptor":
                from copy import deepcopy

                manifest = deepcopy(revision.manifest)
                for member in manifest["files"]:
                    if member["file_name"] == "cold-documents.f32":
                        member["schema_ref"] = "eom://schemas/other/1.0"
                revision.manifest = manifest
            else:
                path = Path(revision.nas_path) / "cold-documents.f32"
                if fault == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"\x00" * path.stat().st_size)
    elif fault == "role":
        admitted.roles[:] = []
    elif fault == "late_role":
        original = admission_module.PinnedArtifactReadContext.revalidate_provenance

        def revoke(reader):
            original(reader)
            admitted.roles[:] = []

        monkeypatch.setattr(
            admission_module.PinnedArtifactReadContext, "revalidate_provenance", revoke
        )
    elif fault == "schema_error":
        from jsonschema import ValidationError

        original = admission_module.parse_embedding_device_benchmark_bytes

        def reject_witness(raw, **kwargs):
            if kwargs:
                raise ValidationError("PRIVATE_WITNESS_MUST_NOT_ESCAPE")
            return original(raw)

        monkeypatch.setattr(
            admission_module, "parse_embedding_device_benchmark_bytes", reject_witness
        )
    else:
        launch = replace(launch, result=series[1].result)
    with (
        pytest.raises((ValueError, OSError)) as caught,
        admitted.publisher.sessions() as session,
        session.begin(),
    ):
        admitted.owner.read_launch_numerics_in_session(session, admitted.request, launch)
    if fault == "schema_error":
        assert str(caught.value) == "BENCHMARK_OWNER_NUMERICAL_MEMBER_INVALID"


@pytest.mark.parametrize("fault", (None, "bytes", "foreign", "late_role"))
def test_cpu_reference_materialization_reuses_exact_same_artifact_scores(
    admitted, tmp_path, monkeypatch, series, fault
):
    launch, _expected, published = published_numerical_launch(admitted, tmp_path, series[0])
    pointer = launch.receipt.evidence
    if fault == "bytes":
        (Path(published.nas_path) / "rank-evidence.f64").write_bytes(b"\x00" * 240)
    elif fault == "foreign":
        pointer = launch.receipt.worker_result
    elif fault == "late_role":
        original = admission_module.PinnedArtifactReadContext.revalidate_provenance

        def revoke(reader):
            original(reader)
            admitted.roles[:] = []

        monkeypatch.setattr(
            admission_module.PinnedArtifactReadContext, "revalidate_provenance", revoke
        )
    with admitted.publisher.sessions() as session, session.begin():
        if fault:
            with pytest.raises(ValueError):
                admitted.owner.read_cpu_numerical_reference_in_session(
                    session, admitted.request, pointer
                )
        else:
            reference = admitted.owner.read_cpu_numerical_reference_in_session(
                session, admitted.request, pointer
            )
            assert reference.pointer == pointer
            assert (
                reference.raw == (Path(published.nas_path) / "near-tie-reference.json").read_bytes()
            )
            assert reference.scores == (Path(published.nas_path) / "rank-evidence.f64").read_bytes()


def test_untrusted_owner_does_not_open_the_numerical_reader():
    with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_READER_OWNER_INVALID"):
        read_completed_benchmark_series_numerics(object(), object(), job_id="job_" + "a" * 32)


def test_original_journal_six_registered_launches_feed_pure_assessor_without_new_jobs_or_dispatch(
    admitted, tmp_path, monkeypatch, series
):
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
    def capacity():
        yield

    monkeypatch.setattr(owner_module, "native_cpu_capacity", capacity)
    monkeypatch.setattr(owner_module, "require_no_active_native_cpu_execution", lambda: None)
    dispatched = []

    class SyntheticExecution:
        def assert_installed(self, request):
            assert request == admitted.request

        def run_and_publish(self, invocation, inputs, authorization):
            authorization.assert_invocation(invocation)
            if invocation.launch_ordinal > 1:
                authorization.require_cpu_reference()
            root = tmp_path / f"launch-{invocation.launch_ordinal}"
            root.mkdir()
            launch, *_ = published_numerical_launch(
                admitted, root, series[invocation.launch_ordinal - 1], invocation=invocation
            )
            dispatched.append(invocation)
            return launch.receipt

    owner = BenchmarkExecutionOwner(
        admitted.publisher.sessions, admission=admitted.owner, execution=SyntheticExecution()
    )
    result = owner.run_launches(admitted.request)
    assert len(dispatched) == 6 and result.state == "VALIDATING_RESULT"
    owner.execution = None
    with owner.sessions() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    first = read_completed_benchmark_series_numerics(owner, admitted.request, job_id=result.job_id)
    second = read_completed_benchmark_series_numerics(owner, admitted.request, job_id=result.job_id)
    assert first == second and len(first.evidence.decisions) == 1050
    assert first.evidence.same_device_failures == first.evidence.component_failures == 0
    with owner.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
        assert session.get(JobRecord, result.job_id).status == "VALIDATING_RESULT"
    assert len(dispatched) == 6
    original_read = owner.journal.read
    with monkeypatch.context() as patch:
        patch.setattr(
            owner.journal,
            "read",
            lambda *args, **kwargs: replace(original_read(*args, **kwargs), job_state="RUNNING"),
        )
        with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_SERIES_NOT_READY"):
            read_completed_benchmark_series_numerics(owner, admitted.request, job_id=result.job_id)
    reads = 0

    def changed_history(*args, **kwargs):
        nonlocal reads
        history = original_read(*args, **kwargs)
        reads += 1
        return history if reads == 1 else replace(history, job_state="COMMITTING")

    with monkeypatch.context() as patch:
        patch.setattr(owner.journal, "read", changed_history)
        with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_HISTORY_CHANGED"):
            read_completed_benchmark_series_numerics(owner, admitted.request, job_id=result.job_id)
    admitted.roles[:] = []
    with pytest.raises(ValueError, match="ADMIN_REQUIRED"):
        read_completed_benchmark_series_numerics(owner, admitted.request, job_id=result.job_id)
