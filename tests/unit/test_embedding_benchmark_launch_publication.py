"""Real synthetic-encoder bytes and tempfiles; no live source, GPU or NAS acceptance."""

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkQueryTiming,
    BenchmarkSession,
    benchmark_ack_for_checkpoint,
)
from eom_catalog_service import embedding_benchmark_launch_publication as publication
from eom_catalog_service.embedding_benchmark_native_observation import (
    ObservedBenchmarkNativeSession,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffIdentity,
    protected_cpu_handoff_directory,
)
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchCompleted,
    benchmark_launch_control_bytes,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError

from tests.unit.embedding_benchmark_control_fixtures import association, completed, prepared
from tests.unit.embedding_device_benchmark_fixtures import staged_inputs, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_benchmark_worker import run_scenario


def output_bundle(tmp_path, monkeypatch, ordinal):
    result, _backend, _events, root, checkpoints = run_scenario(tmp_path, monkeypatch, ordinal)
    assert result.status == "COMPLETED"
    session = BenchmarkSession.model_validate(
        seal(
            dict(
                schema_version="embedding-device-benchmark-session/1.0",
                execution_id=result.execution_id,
                invocation_sha256=result.invocation_sha256,
                launch_ordinal=ordinal,
                checkpoints=[cp.model_dump(mode="json") for cp in checkpoints],
                acks=[
                    benchmark_ack_for_checkpoint(cp).model_dump(mode="json") for cp in checkpoints
                ],
            ),
            "session_sha256",
        )
    )
    timings = result.timings
    assert timings is not None
    cold_end = 100 + timings.startup_ns + timings.load_hash_ns + timings.cold_encode_ns + 1000
    observed = ObservedBenchmarkNativeSession(
        session,
        result.resources,
        cold_end,
        tuple(
            BenchmarkQueryTiming(
                **query.model_dump(mode="json"),
                authorization_ns=1,
                end_to_end_ns=query.encode_ns + 1000,
            )
            for query in timings.query_encode_ns
        ),
        50,
    )
    value = association(ordinal)
    before = prepared(value)
    body = completed(value, before).model_dump(mode="json")
    body.update(
        completed_ns=cold_end + 1000,
        resources=result.resources.model_dump(mode="json") if result.device == "CUDA" else None,
    )
    after = BenchmarkLaunchCompleted.model_validate(seal(body, "completion_sha256"))
    members = {path.name: path.read_bytes() for path in (root / "outputs").iterdir()}
    return SimpleNamespace(
        invocation=worker_invocation(ordinal),
        inputs=staged_inputs(),
        observed=observed,
        prepared=before,
        completion=after,
        members=members,
        result=result,
        root=root,
    )


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_all_six_programs_validate_real_f32_token_resource_and_checkpoint_bytes(
    tmp_path, monkeypatch, ordinal
):
    bundle = output_bundle(tmp_path, monkeypatch, ordinal)
    assert (
        publication.validate_benchmark_output_bytes(
            bundle.invocation, bundle.inputs, bundle.observed, bundle.completion, bundle.members
        ).result
        == bundle.result
    )


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "extra",
        "binary",
        "witness",
        "resources",
        "cold_clock",
        "query_clock",
        "checkpoint",
    ),
)
def test_no_changed_byte_or_clock_can_be_published_as_complete(tmp_path, monkeypatch, fault):
    bundle = output_bundle(tmp_path, monkeypatch, 1)
    if fault == "missing":
        bundle.members.pop("token-witness.json")
    elif fault == "extra":
        bundle.members["unexpected.json"] = b"{}"
    elif fault == "binary":
        bundle.members["cold-documents.f32"] = b"\x00" * len(bundle.members["cold-documents.f32"])
    elif fault == "witness":
        bundle.members["token-witness.json"] += b" "
    elif fault == "resources":
        bundle.members["resources.json"] = b"{}"
    elif fault == "cold_clock":
        bundle.observed = replace(
            bundle.observed, cold_completed_ns=bundle.completion.completed_ns + 1
        )
    elif fault == "query_clock":
        bundle.observed = replace(bundle.observed, queries=bundle.observed.queries[1:])
    else:
        cp = bundle.observed.session.checkpoints[0]
        vector = cp.vector.model_copy(update={"sha256": "sha256:" + "a" * 64})
        body = cp.model_dump(mode="json") | {"vector": vector.model_dump(mode="json")}
        from eom_catalog_contracts.embedding_device_benchmark import BenchmarkCheckpoint

        changed = BenchmarkCheckpoint.model_validate(seal(body, "checkpoint_sha256"))
        body = bundle.observed.session.model_dump(mode="json")
        body["checkpoints"][0] = changed.model_dump(mode="json")
        body["acks"][0] = benchmark_ack_for_checkpoint(changed).model_dump(mode="json")
        session = BenchmarkSession.model_validate(seal(body, "session_sha256"))
        bundle.observed = replace(bundle.observed, session=session)
    with pytest.raises((ValueError, JsonSchemaError)):
        publication.validate_benchmark_output_bytes(
            bundle.invocation, bundle.inputs, bundle.observed, bundle.completion, bundle.members
        )


def test_correctly_rehashed_but_overlapping_supplementary_ranges_are_rejected(
    tmp_path, monkeypatch
):
    bundle = output_bundle(tmp_path, monkeypatch, 1)
    body = bundle.result.model_dump(mode="json")
    index = next(i for i, sample in enumerate(body["vectors"]) if sample["byte_offset"] > 0)
    body["vectors"][index]["byte_offset"] = 0
    body["vectors"][index] = seal(body["vectors"][index], "sample_sha256")
    bundle.members["worker-result.json"] = canonical_json_bytes(seal(body, "result_sha256"))
    with pytest.raises(ValueError, match="VECTOR_RANGE_INVALID"):
        publication.validate_benchmark_output_bytes(
            bundle.invocation, bundle.inputs, bundle.observed, bundle.completion, bundle.members
        )


@pytest.mark.parametrize("revoke_after_commit", (False, True))
@pytest.mark.parametrize("ordinal", (1, 4))
@pytest.mark.parametrize("local_owner", (False, True))
def test_publication_uses_one_separate_job_preserves_bytes_and_late_revocation(
    tmp_path, monkeypatch, revoke_after_commit, ordinal, local_owner, request
):
    bundle = output_bundle(tmp_path, monkeypatch, ordinal)
    workspace = tmp_path / "publication"
    workspace.mkdir(mode=0o700)
    owner_identity = CpuHandoffIdentity(os.getuid(), os.getgid())
    monkeypatch.setattr(publication, "fixed_owner_identity", lambda: owner_identity)
    monkeypatch.setattr(publication, "BENCHMARK_HANDOFF_ROOT", bundle.root.parent)

    def synthetic_directory(path, **kwargs):
        if kwargs["uid"] == 0:
            kwargs["uid"] = os.getuid()
        return protected_cpu_handoff_directory(path, **kwargs)

    monkeypatch.setattr(publication, "protected_cpu_handoff_directory", synthetic_directory)
    actual_read = publication.read_protected_cpu_handoff_member

    def synthetic_read(directory, name, **kwargs):
        if kwargs["uid"] == 0:
            kwargs["uid"] = os.getuid()
        return actual_read(directory, name, **kwargs)

    monkeypatch.setattr(publication, "read_protected_cpu_handoff_member", synthetic_read)
    for name, record in (
        ("root-prepared.json", bundle.prepared),
        ("root-completion.json", bundle.completion),
    ):
        path = bundle.root / name
        path.write_bytes(benchmark_launch_control_bytes(record))
        path.chmod(0o640)
    calls, published_members = [], []
    actual_owner = None
    if local_owner:
        from tests.unit.test_control_file_set_publication import _publisher

        owner_root = tmp_path / "actual-file-set-owner"
        owner_root.mkdir()
        actual_owner, engine = _publisher(owner_root)
        request.addfinalizer(engine.dispose)
    authorization = object.__new__(BenchmarkLaunchAuthorization)

    def authorize(_self, invocation):
        assert invocation == bundle.invocation
        calls.append("authorize")
        if revoke_after_commit and calls == ["authorize", "authorize", "publish", "authorize"]:
            raise ValueError("synthetic source revoked after commit")

    monkeypatch.setattr(BenchmarkLaunchAuthorization, "assert_invocation", authorize)

    def publish(**kwargs):
        calls.append("publish")
        assert kwargs["primary_file"] == "worker-result.json"
        assert kwargs["artifact_type"] == "control_embedding_benchmark_launch"
        assert len(kwargs["members"]) == (32 if ordinal == 1 else 8)
        assert tuple(member.file_name for member in kwargs["members"]) == tuple(
            sorted(member.file_name for member in kwargs["members"])
        )
        for member in kwargs["members"]:
            raw = member.source.read_bytes()
            assert member.sha256 == publication.sha256_bytes(raw)
            assert member.bytes == len(raw)
            if member.file_name.endswith(".f32"):
                assert (
                    member.schema_ref == "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"
                )
            published_members.append((member.file_name, raw))
        identity = kwargs.get("identity")
        if actual_owner is not None:
            if identity is not None:
                return actual_owner.publish_identified_first_observation(**kwargs)
            return actual_owner.publish_first_observation(**kwargs)
        return PublishedControlFileSet(
            identity.job_id if identity else "job_" + "f" * 32,
            identity.artifact_id if identity else "artifact_" + "f" * 32,
            identity.artifact_revision_id if identity else "rev_" + "f" * 32,
            "worker-result.json",
            publication.sha256_bytes(bundle.members["worker-result.json"]),
            "sha256:" + "a" * 64,
            "synthetic-not-NAS",
        )

    publisher = publication.BenchmarkLaunchArtifactPublisher(
        SimpleNamespace(
            settings=SimpleNamespace(workspace_root=workspace),
            publish_first_observation=publish,
            publish_identified_first_observation=publish,
        ),
        source_commit="a" * 40,
    )
    if revoke_after_commit:
        with pytest.raises(ValueError, match="revoked after commit"):
            publisher.publish(
                bundle.invocation,
                bundle.inputs,
                bundle.observed,
                bundle.prepared,
                bundle.completion,
                authorization=authorization,
            )
    else:
        receipt = publisher.publish(
            bundle.invocation,
            bundle.inputs,
            bundle.observed,
            bundle.prepared,
            bundle.completion,
            authorization=authorization,
        )
        assert receipt.job_id == bundle.invocation.job_id
        assert receipt.worker_result.artifact_id == receipt.evidence.artifact_id
        assert receipt.session.artifact_revision_id == receipt.evidence.artifact_revision_id
        if ordinal == 1:
            from eom_catalog_service.embedding_benchmark_cpu_reference import (
                validate_cpu_benchmark_reference,
            )

            from tests.unit.embedding_device_benchmark_fixtures import owner_request

            saved = dict(published_members)
            reference = validate_cpu_benchmark_reference(
                owner_request(),
                receipt.evidence,
                saved["near-tie-reference.json"],
                saved["rank-evidence.f64"],
            )
            assert reference.score_binary.artifact_id == receipt.worker_result.artifact_id
    assert calls == ["authorize", "authorize", "publish", "authorize"]
    import json

    cold = json.loads(dict(published_members)["cold-timing.json"])
    assert (
        cold["end_to_end_ns"]
        == bundle.observed.cold_completed_ns - bundle.observed.owner_started_ns
    )
    assert all(dict(published_members)[name] == raw for name, raw in bundle.members.items())
    assert all(
        (bundle.root / "outputs" / name).read_bytes() == raw for name, raw in bundle.members.items()
    )
