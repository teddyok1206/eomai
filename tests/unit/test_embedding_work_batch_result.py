"""Local result/FD protocol tests over synthetic vectors; no model, DB or GPU calls."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_contracts.embedding_work_batch_result import (
    build_embedding_work_batch_result,
    embedding_work_batch_result_bytes,
    parse_embedding_work_batch_result,
    validate_embedding_work_batch_result,
)
from eom_catalog_service import embedding_native_stdio as handoff
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionResources,
    execute_embedding_work_batch,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_work_batch import Fence, batch_body

ERRORS = (ValueError, SchemaError)


def local_case(purpose="REFERENCE_QUERY", device="CPU", count=2):
    batch = EmbeddingWorkBatchInput.model_validate(batch_body(purpose, count, device=device))
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size = batch.children[0].request.batch_size
    backend.threads = batch.children[0].request.threads
    life = []

    @contextmanager
    def scope():
        life.append("open")
        try:
            yield backend
        finally:
            life.append("closed")

    resources = EmbeddingWorkBatchExecutionResources(
        batch.resource_profile_sha256, batch.timeout_seconds, batch.vector_max_bytes
    )
    return batch, backend, scope, resources, life


@pytest.mark.parametrize("purpose", ["REFERENCE_QUERY", "DOCUMENT"])
@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_parent_result_preserves_each_child_and_contiguous_original_vectors(purpose, device):
    request, backend, scope, resources, life = local_case(purpose, device)
    encoded = execute_embedding_work_batch(
        request, resources=resources, backend_scope=scope, fence=Fence()
    )
    binary = b"".join(child.vectors for child in encoded.children)
    result = build_embedding_work_batch_result(
        request, tuple(child.result for child in encoded.children), sha256_bytes(binary)
    )
    validate_embedding_work_batch_result(request, result)
    assert life == ["open", "closed"] and len(backend.calls) == 2
    assert len(result.children) == 2 and result.vectors.byte_count == len(binary)
    ranges = validate_embedding_work_batch_binary(request, result, binary)
    assert len(ranges) == 2
    assert all(view.readonly and view.obj is binary for view in ranges)
    assert (
        parse_embedding_work_batch_result(json.loads(embedding_work_batch_result_bytes(result)))
        == result
    )
    for source, child in zip(encoded.children, result.children, strict=True):
        assert source.result == child.result
        shard = child.result.shard
        selected = binary[child.vector_offset : child.vector_offset + shard.binary.byte_count]
        assert selected == source.vectors
        read_unit_vectors(
            selected,
            dimension=shard.dimension,
            row_count=shard.row_count,
            expected_sha256=shard.binary.sha256,
        )


@pytest.mark.parametrize("fault", ["length", "hash", "child_hash", "norm", "mutable"])
def test_owner_binary_read_rejects_corruption_even_with_resealed_parent(fault):
    request, _, scope, resources, _ = local_case()
    encoded = execute_embedding_work_batch(
        request, resources=resources, backend_scope=scope, fence=Fence()
    )
    binary = b"".join(child.vectors for child in encoded.children)
    result = build_embedding_work_batch_result(
        request, tuple(child.result for child in encoded.children), sha256_bytes(binary)
    )
    if fault == "length":
        payload = binary[:-1]
    elif fault == "mutable":
        payload = bytearray(binary)
    else:
        payload = bytes(len(binary))
        if fault in ("child_hash", "norm"):
            body = result.model_dump(mode="json")
            body["vectors"]["sha256"] = sha256_bytes(payload)
            if fault == "norm":
                for child in body["children"]:
                    shard = child["result"]["shard"]
                    shard["binary"]["sha256"] = sha256_bytes(bytes(shard["binary"]["byte_count"]))
                    child["result"]["shard"] = seal(shard, "shard_sha256")
                    child["result"] = seal(child["result"], "result_sha256")
            result = parse_embedding_work_batch_result(seal(body, "result_sha256"))
    with pytest.raises(ValueError, match=r"LENGTH_MISMATCH|HASH_MISMATCH|NORM_INVALID"):
        validate_embedding_work_batch_binary(request, result, payload)


@pytest.fixture
def result_case():
    request, _, scope, resources, _ = local_case()
    encoded = execute_embedding_work_batch(
        request, resources=resources, backend_scope=scope, fence=Fence()
    )
    result = build_embedding_work_batch_result(
        request,
        tuple(child.result for child in encoded.children),
        sha256_bytes(b"".join(child.vectors for child in encoded.children)),
    )
    return request, result


@pytest.mark.parametrize(
    "fault", ["overlap", "gap", "unaligned", "total", "duplicate", "route", "request", "reorder"]
)
def test_resealed_result_cannot_hide_wrong_ranges_ownership_or_order(result_case, fault):
    request, result = result_case
    body = deepcopy(result.model_dump(mode="json"))
    if fault == "overlap":
        body["children"][1]["vector_offset"] = 0
    elif fault == "gap":
        body["children"][1]["vector_offset"] += 4
    elif fault == "unaligned":
        body["children"][1]["vector_offset"] += 1
    elif fault == "total":
        body["vectors"]["byte_count"] += 4
    elif fault == "duplicate":
        body["children"][1]["result"] = body["children"][0]["result"]
    elif fault in ("request", "route"):
        body["request_sha256" if fault == "request" else "routing_decision_sha256"] = (
            "sha256:" + "9" * 64
        )
    else:
        body["children"][0]["result"], body["children"][1]["result"] = (
            body["children"][1]["result"],
            body["children"][0]["result"],
        )
    with pytest.raises(ERRORS):
        changed = parse_embedding_work_batch_result(seal(body, "result_sha256"))
        validate_embedding_work_batch_result(request, changed)


def test_copied_parent_and_nested_extras_are_not_sanitized(result_case):
    request, result = result_case
    for forged in (
        result.model_copy(update={"extra": True}),
        result.model_copy(update={"vectors": result.vectors.model_copy(update={"extra": True})}),
        result.model_copy(
            update={"children": (result.children[0].model_copy(update={"extra": True}),)}
        ),
    ):
        with pytest.raises(ERRORS):
            validate_embedding_work_batch_result(request, forged)


@pytest.fixture
def batch_descriptors(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "_ROOT_UID", os.getuid())
    batch, backend, scope, resources, life = local_case()
    source = tmp_path / "input.json"
    source.write_bytes(canonical_json_bytes(batch.model_dump(mode="json")))
    source.chmod(0o600)
    descriptors = [os.open(source, os.O_RDONLY)]
    try:
        for name in ("result.json", "vectors.f32"):
            descriptor = os.open(tmp_path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            os.fchmod(descriptor, 0o640)
            descriptors.append(descriptor)
        yield (
            batch,
            backend,
            scope,
            resources,
            life,
            handoff.NativeEmbeddingDescriptors(*descriptors),
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def test_protected_batch_fd_writes_binary_then_metadata_after_one_model_scope(
    batch_descriptors, tmp_path, monkeypatch
):
    batch, backend, scope, resources, life, descriptors = batch_descriptors
    writes = []
    original_write = os.write

    def tracked_write(descriptor, payload):
        writes.append(descriptor)
        return original_write(descriptor, payload)

    monkeypatch.setattr(os, "write", tracked_write)
    handoff.run_native_embedding_work_batch_descriptors(
        descriptors,
        scope,
        resources=resources,
        maximum_total_output_bytes=64 * 1024**2,
        fence=Fence(),
    )
    result = parse_embedding_work_batch_result(json.loads((tmp_path / "result.json").read_bytes()))
    validate_embedding_work_batch_result(batch, result)
    payload = (tmp_path / "vectors.f32").read_bytes()
    assert sha256_bytes(payload) == result.vectors.sha256
    assert len(payload) == result.vectors.byte_count
    assert writes == [descriptors.vectors, descriptors.vectors, descriptors.result]
    assert life == ["open", "closed"] and len(backend.calls) == 2


def test_aggregate_metadata_budget_is_enforced_before_any_output_write(batch_descriptors, tmp_path):
    batch, _, scope, resources, life, descriptors = batch_descriptors
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="RESULT_INVALID"):
        handoff.run_native_embedding_work_batch_descriptors(
            descriptors,
            scope,
            resources=resources,
            maximum_total_output_bytes=batch.expected_vector_bytes + 1,
            fence=Fence(),
        )
    assert life == ["open", "closed"]
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""


def test_partial_binary_io_failure_never_writes_success_or_reencodes(
    batch_descriptors, tmp_path, monkeypatch
):
    _, backend, scope, resources, life, descriptors = batch_descriptors
    original_write = os.write

    def failing_write(descriptor, payload):
        if descriptor == descriptors.vectors:
            original_write(descriptor, payload[:7])
            raise OSError("private input must not leak")
        return original_write(descriptor, payload)

    monkeypatch.setattr(os, "write", failing_write)
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="IO_FAILED") as error:
        handoff.run_native_embedding_work_batch_descriptors(
            descriptors,
            scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            fence=Fence(),
        )
    assert "private" not in str(error.value)
    assert (tmp_path / "result.json").read_bytes() == b""
    assert len((tmp_path / "vectors.f32").read_bytes()) == 7
    assert life == ["open", "closed"] and len(backend.calls) == 2


def test_batch_output_alias_is_rejected_before_model_load(batch_descriptors, tmp_path):
    _, backend, scope, resources, life, descriptors = batch_descriptors
    alias = replace(descriptors, result=descriptors.vectors)
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_work_batch_descriptors(
            alias,
            scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            fence=Fence(),
        )
    assert not life and not backend.calls
    assert (tmp_path / "result.json").read_bytes() == b""


def test_batch_input_epoch_change_after_scope_cleanup_blocks_output(batch_descriptors, tmp_path):
    _, backend, scope, resources, life, descriptors = batch_descriptors

    @contextmanager
    def changed_scope():
        with scope() as actual:
            yield actual
        (tmp_path / "input.json").write_bytes(b"changed input")

    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="INPUT_CHANGED"):
        handoff.run_native_embedding_work_batch_descriptors(
            descriptors,
            changed_scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            fence=Fence(),
        )
    assert life == ["open", "closed"] and len(backend.calls) == 2
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""


def test_batch_revalidates_child_binary_before_any_write(batch_descriptors, tmp_path, monkeypatch):
    batch, backend, scope, resources, life, descriptors = batch_descriptors
    encoded = execute_embedding_work_batch(
        batch, resources=resources, backend_scope=scope, fence=Fence()
    )
    first = encoded.children[0]
    forged = replace(
        encoded,
        children=(replace(first, vectors=bytes(len(first.vectors))), *encoded.children[1:]),
    )
    monkeypatch.setattr(handoff, "execute_embedding_work_batch", lambda *args, **kwargs: forged)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        handoff.run_native_embedding_work_batch_descriptors(
            descriptors,
            scope,
            resources=resources,
            maximum_total_output_bytes=64 * 1024**2,
            fence=Fence(),
        )
    assert life == ["open", "closed"] and len(backend.calls) == 2
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""
