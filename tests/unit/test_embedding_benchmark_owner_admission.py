"""Actual local policy Artifact resolver; synthetic Identity/source, NOT live compute admission."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    BENCHMARK_POLICY_ARTIFACT_TYPE,
    BENCHMARK_POLICY_V12_SCHEMA_REF,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_owner_admission as module
from eom_catalog_service.embedding_benchmark_owner_admission import (
    BenchmarkOwnerConfiguration,
    CatalogBenchmarkOwnerAdmission,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.embedding_device_benchmark_fixtures import worker_result
from tests.unit.test_control_file_set_publication import _publisher

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    publisher, engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    request, inputs = benchmark_case()
    policy_publisher = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    published = policy_publisher.publish_benchmark_policy(
        request.execution_policy, idempotency_key="synthetic-benchmark-policy", created_at=NOW
    )
    config = BenchmarkOwnerConfiguration(
        request.request_sha256, published.member, published.semantic_sha256
    )
    owner = object.__new__(CatalogBenchmarkOwnerAdmission)
    owner.configuration = config
    owner._settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    owner._control = Mock(capture=SimpleNamespace(operator_id=request.operator_audit_id))
    owner._source = SyntheticBenchmarkAdmission(request, inputs)
    roles = ["ADMIN"]
    monkeypatch.setattr(
        module,
        "active_role_assignments",
        lambda *_: [(None, SimpleNamespace(role_key=role)) for role in roles],
    )
    yield SimpleNamespace(
        owner=owner,
        publisher=publisher,
        request=request,
        inputs=inputs,
        published=published,
        policy_publisher=policy_publisher,
        roles=roles,
    )
    engine.dispose()


def test_exact_selected_policy_uses_registered_artifact_and_same_current_root(admitted):
    value = admitted
    assert (
        value.policy_publisher.publish_benchmark_policy(
            value.request.execution_policy,
            idempotency_key="synthetic-benchmark-policy",
            created_at=NOW,
        )
        == value.published
    )
    with value.publisher.sessions() as session, session.begin():
        with value.owner.admit_execution_in_session(session, value.request) as inputs:
            assert inputs == value.inputs
            assert value.owner._control.fence_current_operator.call_count == 1
        assert value.owner._control.fence_current_operator.call_count == 2
        artifact = session.get(ArtifactRecord, value.published.member.artifact_id)
        assert artifact.artifact_type == BENCHMARK_POLICY_ARTIFACT_TYPE
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize(
    "fault", ("actor", "request", "semantic", "raw", "role", "expired", "producer")
)
def test_policy_publication_and_workflow_start_alone_are_not_compute_admission(admitted, fault):
    value, request = admitted, admitted.request
    config = value.owner.configuration
    if fault == "actor":
        value.owner._control.capture.operator_id = "operator_" + "f" * 32
    elif fault == "request":
        value.owner.configuration = replace(config, request_sha256="sha256:" + "f" * 64)
    elif fault == "semantic":
        value.owner.configuration = replace(config, execution_policy_sha256="sha256:" + "f" * 64)
    elif fault == "raw":
        pointer = config.execution_policy.model_copy(update={"sha256": "sha256:" + "f" * 64})
        value.owner.configuration = replace(config, execution_policy=pointer)
    elif fault == "role":
        value.roles[:] = ["WORKER"]
    elif fault == "expired":
        value.owner._control.fence_current_operator.side_effect = ValueError("SYNTHETIC_EXPIRED")
    elif fault == "producer":
        with value.publisher.sessions() as session, session.begin():
            session.get(JobRecord, value.published.owner_job_id).status = "FAILED"
    with (
        pytest.raises(ValueError),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit_execution_in_session(session, request),
    ):
        pytest.fail("invalid admission reached body")
    assert value.owner._source.entered == 0


def test_late_revocation_is_not_hidden_by_policy_or_source_success(admitted):
    value = admitted
    with (
        pytest.raises(ValueError, match="ADMIN_REQUIRED"),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit_execution_in_session(session, value.request),
    ):
        value.roles[:] = []


@pytest.mark.parametrize(
    "field,value",
    (
        ("member_path", "input.json"),
        ("media_type", "text/plain"),
        ("schema_ref", "eom://schemas/workflow/local-embedding-execution-policy/1.0"),
    ),
)
def test_other_purpose_policy_is_not_a_benchmark_selection(admitted, field, value):
    config = admitted.owner.configuration
    with pytest.raises(ValueError, match="CONFIGURATION_INVALID"):
        replace(config, execution_policy=config.execution_policy.model_copy(update={field: value}))


def test_v12_policy_pointer_is_valid_but_does_not_match_v10_request(admitted):
    config = admitted.owner.configuration
    pointer = config.execution_policy.model_copy(
        update={"schema_ref": BENCHMARK_POLICY_V12_SCHEMA_REF}
    )
    selected = replace(config, execution_policy=pointer)
    assert selected.execution_policy.schema_ref == BENCHMARK_POLICY_V12_SCHEMA_REF
    admitted.owner.configuration = selected
    with (
        pytest.raises(ValueError, match="BENCHMARK_OWNER_SELECTION_MISMATCH"),
        admitted.publisher.sessions() as session,
        session.begin(),
        admitted.owner.admit_execution_in_session(session, admitted.request),
    ):
        pytest.fail("foreign policy version reached source admission")
    assert admitted.owner._source.entered == 0


def test_raw_publication_hash_and_semantic_policy_identity_remain_distinct(admitted):
    value = admitted
    assert value.published.semantic_sha256 == value.request.execution_policy.policy_sha256
    assert value.published.member.sha256 != value.published.semantic_sha256
    assert canonical_json_bytes(value.request.execution_policy) == embedding_device_benchmark_bytes(
        value.request.execution_policy
    )


def test_dto_or_audit_actor_cannot_construct_the_real_identity_adapter(admitted):
    with pytest.raises(ValueError):
        CatalogBenchmarkOwnerAdmission(
            admitted.publisher.engine,
            admitted.owner.configuration,
            capture=SimpleNamespace(operator_id=admitted.request.operator_audit_id),
            session_fence=Mock(),
            settings=admitted.owner._settings,
        )


def test_result_reader_uses_explicit_current_root_and_registered_member(admitted, tmp_path):
    value = admitted
    raw = embedding_device_benchmark_bytes(worker_result())
    path = tmp_path / "worker-result.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    schema = EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult"
    published = value.publisher.publish(
        members=(
            ControlFileSetMember(
                path.name, path, sha256_bytes(raw), len(raw), schema, "application/json"
            ),
        ),
        primary_file=path.name,
        artifact_type=BENCHMARK_LAUNCH_ARTIFACT_TYPE,
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key="synthetic-result-reader",
        source_commit="a" * 40,
        created_at=NOW,
    )
    pointer = ArtifactMemberPointer(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path=path.name,
        schema_ref=schema,
        media_type="application/json",
        sha256=sha256_bytes(raw),
    )
    with value.publisher.sessions() as session, session.begin():
        assert value.owner.read_in_session(session, value.request, pointer) == raw
    assert value.owner._source.entered == value.owner._source.exited == 1
    value.roles[:] = []
    with (
        pytest.raises(ValueError, match="ADMIN_REQUIRED"),
        value.publisher.sessions() as session,
        session.begin(),
    ):
        value.owner.read_in_session(session, value.request, pointer)


@pytest.mark.parametrize(
    "field,invalid",
    (
        ("member_path", "resources.json"),
        ("schema_ref", "eom://schemas/other/1.0"),
        ("media_type", "image/png"),
    ),
)
def test_result_reader_rejects_wrong_member_contract_before_artifact_io(admitted, field, invalid):
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="worker-result.json",
        schema_ref=EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult",
        media_type="application/json",
        sha256="sha256:" + "c" * 64,
    ).model_copy(update={field: invalid})
    with (
        pytest.raises(ValueError, match="RESULT_POINTER_INVALID"),
        admitted.publisher.sessions() as session,
        session.begin(),
    ):
        admitted.owner.read_in_session(session, admitted.request, pointer)
    assert admitted.owner._source.entered == 0


@pytest.mark.parametrize("fault", (None, "bytes", "role", "foreign-artifact"))
def test_cpu_reference_reader_uses_registered_same_artifact_scores_and_current_authority(
    admitted, tmp_path, fault
):
    from pathlib import Path

    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity

    from tests.unit.embedding_device_benchmark_fixtures import worker_invocation
    from tests.unit.inference_transfer_embedding_fixtures import seal
    from tests.unit.test_embedding_benchmark_cpu_reference import cpu_reference

    value = admitted
    body = worker_invocation(1).model_dump(mode="json")
    inputs_raw = embedding_device_benchmark_bytes(value.inputs)
    body.update(
        benchmark_id=value.request.benchmark_id,
        benchmark_revision_id=value.request.benchmark_revision_id,
        owner_request_sha256=value.request.request_sha256,
        local_input=dict(
            member_name="benchmark-inputs.json",
            sha256=sha256_bytes(inputs_raw),
            byte_count=len(inputs_raw),
        ),
    )
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    identity = ControlFileSetIdentity("job_" + "c" * 32, "artifact_" + "d" * 32, "rev_" + "e" * 32)
    reference, pointer, raw, scores = cpu_reference(
        invocation, value.request, identity.artifact_id, identity.artifact_revision_id
    )
    if fault == "foreign-artifact":
        body = reference.model_dump(mode="json")
        body["score_binary"]["artifact_id"] = "artifact_" + "f" * 32
        from eom_catalog_contracts.embedding_device_benchmark import BenchmarkNearTieReference

        reference = BenchmarkNearTieReference.model_validate(seal(body, "reference_sha256"))
        raw = embedding_device_benchmark_bytes(reference)
        pointer = pointer.model_copy(update={"sha256": sha256_bytes(raw)})
    members = []
    result_schema = EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult"
    for name, payload, schema, media in (
        (
            "worker-result.json",
            embedding_device_benchmark_bytes(worker_result()),
            result_schema,
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
    published = value.publisher.publish_identified_first_observation(
        identity=identity,
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file="worker-result.json",
        artifact_type=BENCHMARK_LAUNCH_ARTIFACT_TYPE,
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key="synthetic-cpu-reference-reader",
        source_commit="a" * 40,
    )
    if fault == "bytes":
        location = Path(published.nas_path) / "rank-evidence.f64"
        location.chmod(0o600)
        location.write_bytes(b"\x00" * len(scores))
    elif fault == "role":
        value.roles[:] = []
    with value.publisher.sessions() as session, session.begin():
        if fault is None:
            assert value.owner.read_in_session(session, value.request, pointer) == raw
        else:
            with pytest.raises((ValueError, RuntimeError)):
                value.owner.read_in_session(session, value.request, pointer)
