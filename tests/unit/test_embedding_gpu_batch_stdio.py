"""Real local FD/Unix composition, synthetic numeric backend, no root/GPU/model execution."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_contracts.embedding_work_batch_result import (
    parse_supported_embedding_work_batch_result,
)
from eom_catalog_service import embedding_native_stdio as handoff
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_embedding_gpu_control_channel import endpoints
from tests.unit.test_embedding_work_batch_result import local_case
from tests.unit.test_public_solution_work_batch import public_case


@pytest.fixture
def cuda_descriptors(tmp_path, monkeypatch, request):
    monkeypatch.setattr(handoff, "_ROOT_UID", os.geteuid())
    batch, backend, scope, resources, life = (
        public_case(device="CUDA")
        if getattr(request, "param", None) == "public"
        else local_case(device="CUDA")
    )
    source = tmp_path / "input.json"
    source.write_bytes(canonical_json_bytes(batch.model_dump(mode="json")))
    source.chmod(0o600)
    fds = [os.open(source, os.O_RDONLY)]
    try:
        for name in ("result.json", "vectors.f32"):
            descriptor = os.open(tmp_path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            os.fchmod(descriptor, 0o640)
            fds.append(descriptor)
        yield batch, backend, scope, resources, life, handoff.NativeEmbeddingDescriptors(*fds)
    finally:
        for descriptor in fds:
            os.close(descriptor)


@pytest.mark.parametrize("ack", ["verified", "lost"])
@pytest.mark.parametrize("cuda_descriptors", ["legacy", "public"], indirect=True)
def test_granted_fd_batch_reads_once_and_waits_for_actual_output_ack(
    cuda_descriptors, tmp_path, monkeypatch, ack
):
    batch, backend, scope, resources, life, descriptors = cuda_descriptors
    public = batch.schema_version.endswith("/2.0")
    entry = (
        handoff.run_granted_supported_embedding_gpu_batch_descriptors
        if public
        else handoff.run_granted_native_embedding_gpu_batch_descriptors
    )
    reads, authorized = [], []
    read_payload = handoff._read_payload

    def counted_read(descriptor, initial):
        reads.append(descriptor)
        return read_payload(descriptor, initial)

    monkeypatch.setattr(handoff, "_read_payload", counted_read)
    with endpoints(batch=batch, bound=False) as (root, worker, case, *_):
        assert batch == case[6]
        root.bind_batch(
            batch, input_raw_sha256=sha256_bytes(case[7]), input_byte_count=len(case[7])
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                entry,
                descriptors,
                scope,
                resources=resources,
                maximum_total_output_bytes=64 * 1024**2,
                channel=worker,
            )
            while (claim := root.authorize_next(lambda check: authorized.append(check))) is None:
                pass
            assert not future.done()
            assert (
                life == (["load", "close"] if public else ["open", "closed"])
                and len(backend.calls) == 2
            )
            assert len(authorized) == 12 and reads == [descriptors.input]
            raw = (tmp_path / "result.json").read_bytes()
            binary = (tmp_path / "vectors.f32").read_bytes()
            result = parse_supported_embedding_work_batch_result(json.loads(raw))
            assert claim.result_raw_sha256 == sha256_bytes(raw)
            assert claim.result_sha256 == result.result_sha256
            assert claim.vectors_sha256 == sha256_bytes(binary)
            validate_embedding_work_batch_binary(batch, result, binary)

            if ack == "lost":
                root.close()
                with pytest.raises(handoff.NativeEmbeddingHandoffError, match="EXECUTION_FAILED"):
                    future.result(timeout=2)
                # Complete local outputs remain; do not re-encode or claim fallback/success.
                assert (tmp_path / "result.json").read_bytes() == raw
                assert (tmp_path / "vectors.f32").read_bytes() == binary
                assert len(backend.calls) == 2
            else:

                def verify(actual):
                    assert actual == claim
                    assert (tmp_path / "result.json").read_bytes() == raw
                    assert (tmp_path / "vectors.f32").read_bytes() == binary

                root.acknowledge_result(verify)
                assert future.result(timeout=2) == result


@pytest.mark.parametrize(
    "entry",
    [
        handoff.run_granted_native_embedding_gpu_batch_descriptors,
        handoff.run_granted_supported_embedding_gpu_batch_descriptors,
    ],
)
def test_ungranted_worker_cannot_read_input_or_open_model(cuda_descriptors, monkeypatch, entry):
    _, backend, scope, resources, life, descriptors = cuda_descriptors
    reads = []
    monkeypatch.setattr(handoff, "_read_payload", lambda *args: reads.append(args))
    with (
        endpoints(ready=False, granted=False, bound=False) as (_, worker, *_),
        pytest.raises(handoff.NativeEmbeddingHandoffError, match="EXECUTION_FAILED"),
    ):
        entry(
            descriptors,
            scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            channel=worker,
        )
    assert not reads and not life and not backend.calls
    assert os.lseek(descriptors.input, 0, os.SEEK_CUR) == 0


@pytest.mark.parametrize(
    "entry",
    [
        handoff.run_granted_native_embedding_gpu_batch_descriptors,
        handoff.run_granted_supported_embedding_gpu_batch_descriptors,
    ],
)
def test_different_valid_input_is_not_covered_by_original_grant(cuda_descriptors, tmp_path, entry):
    _, backend, scope, resources, life, descriptors = cuda_descriptors
    other_batch, *_ = local_case(device="CUDA", count=1)
    (tmp_path / "input.json").write_bytes(canonical_json_bytes(other_batch.model_dump(mode="json")))
    with (
        endpoints(bound=False) as (_, worker, *_),
        pytest.raises(handoff.NativeEmbeddingHandoffError, match="EXECUTION_FAILED"),
    ):
        entry(
            descriptors,
            scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            channel=worker,
        )
    assert not life and not backend.calls
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""


@pytest.mark.parametrize("cuda_descriptors", ["public"], indirect=True)
def test_legacy_gpu_fd_parser_stays_closed_to_public_batch(cuda_descriptors, tmp_path):
    batch, backend, scope, resources, life, descriptors = cuda_descriptors
    with (
        endpoints(batch=batch, bound=False) as (_, channel, *_),
        pytest.raises(handoff.NativeEmbeddingHandoffError),
    ):
        handoff.run_granted_native_embedding_gpu_batch_descriptors(
            descriptors,
            scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            channel=channel,
        )
    assert not life and not backend.calls
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""
