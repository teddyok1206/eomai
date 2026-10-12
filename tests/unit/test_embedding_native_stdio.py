"""Synthetic protected-FD seam tests; no root install, GPU, source rights or launch."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_catalog_service import embedding_native_stdio as handoff
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_catalog_service.embedding_execution_ports import NativeEmbeddingBackend
from eom_identifiers import canonical_json_bytes

from tests.unit.inference_transfer_embedding_fixtures import embedding_input
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend


@pytest.fixture
def descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[handoff.NativeEmbeddingDescriptors]:
    monkeypatch.setattr(handoff, "_ROOT_UID", os.getuid())
    (tmp_path / "input.json").write_bytes(
        canonical_json_bytes(embedding_input().model_dump(mode="json"))
    )
    (tmp_path / "input.json").chmod(0o600)
    outputs = []
    for name in ("result.json", "vectors.f32"):
        descriptor = os.open(tmp_path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        os.fchmod(descriptor, 0o640)
        outputs.append(descriptor)
    source = os.open(tmp_path / "input.json", os.O_RDONLY)
    try:
        yield handoff.NativeEmbeddingDescriptors(source, *outputs)
    finally:
        for descriptor in (source, *outputs):
            os.close(descriptor)


class BackendScope:
    def __init__(self) -> None:
        self.backend = SyntheticNativeBackend(embedding_input().space)
        self.events: list[str] = []

    @contextmanager
    def __call__(self) -> Iterator[NativeEmbeddingBackend]:
        self.events.append("construct")
        try:
            yield self.backend
        finally:
            self.events.append("exit")


def test_native_input_outputs_exact_binary_then_canonical_result(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = BackendScope()
    sync_order = []
    actual_fsync = os.fsync

    def synced(descriptor: int) -> None:
        sync_order.append(descriptor)
        actual_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", synced)
    handoff.run_native_embedding_descriptors(descriptors, scope)
    payload = (tmp_path / "result.json").read_bytes()
    result = parse_incremental_embedding_result(json.loads(payload))
    validate_incremental_embedding_result(embedding_input(), result)
    assert payload == canonical_json_bytes(result.model_dump(mode="json"))
    vectors = (tmp_path / "vectors.f32").read_bytes()
    assert (
        read_unit_vectors(
            vectors,
            dimension=result.shard.dimension,
            row_count=result.shard.row_count,
            expected_sha256=result.shard.binary.sha256,
        )[0][0]
        == 1.0
    )
    assert sync_order == [descriptors.vectors, descriptors.result]
    assert scope.events == ["construct", "exit"]
    assert len(scope.backend.calls) == 1
    assert not (tmp_path / "shard.json").exists()


@pytest.mark.parametrize("field", ["input", "result", "vectors"])
@pytest.mark.parametrize("mode", [0o666, 0o400, 0o777])
def test_wrong_descriptor_mode_never_constructs_backend(
    descriptors: handoff.NativeEmbeddingDescriptors, field: str, mode: int
) -> None:
    os.fchmod(getattr(descriptors, field), mode)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


@pytest.mark.parametrize("field", ["result", "vectors"])
def test_nonempty_output_is_preserved_without_backend_creation(
    descriptors: handoff.NativeEmbeddingDescriptors, field: str, tmp_path: Path
) -> None:
    target = getattr(descriptors, field)
    os.write(target, b"previous-partial-output")
    os.lseek(target, 0, os.SEEK_SET)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events
    assert (
        tmp_path / ("result.json" if field == "result" else "vectors.f32")
    ).read_bytes() == b"previous-partial-output"


def test_same_fd_alias_is_refused(descriptors: handoff.NativeEmbeddingDescriptors) -> None:
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(
            replace(descriptors, vectors=descriptors.result), scope
        )
    assert not scope.events


def test_distinct_fd_same_inode_is_refused(descriptors: handoff.NativeEmbeddingDescriptors) -> None:
    duplicate = os.dup(descriptors.result)
    scope = BackendScope()
    try:
        with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_ALIAS"):
            handoff.run_native_embedding_descriptors(replace(descriptors, vectors=duplicate), scope)
    finally:
        os.close(duplicate)
    assert not scope.events


@pytest.mark.parametrize("field", ["input", "result", "vectors"])
def test_nonzero_offset_is_refused(
    descriptors: handoff.NativeEmbeddingDescriptors, field: str
) -> None:
    os.lseek(getattr(descriptors, field), 1, os.SEEK_SET)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


@pytest.mark.parametrize(
    "payload", [b"{}", b"{", b"[]", b'{"schema_version":1,"schema_version":2}']
)
def test_invalid_json_never_constructs_backend(
    descriptors: handoff.NativeEmbeddingDescriptors, tmp_path: Path, payload: bytes
) -> None:
    (tmp_path / "input.json").write_bytes(payload)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="REQUEST_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


def test_noncanonical_input_is_refused_before_backend_creation(
    descriptors: handoff.NativeEmbeddingDescriptors, tmp_path: Path
) -> None:
    (tmp_path / "input.json").write_bytes(
        canonical_json_bytes(embedding_input().model_dump(mode="json")) + b"\n"
    )
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="REQUEST_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


def test_input_change_in_construction_closes_scope_without_inference(
    descriptors: handoff.NativeEmbeddingDescriptors, tmp_path: Path
) -> None:
    scope = BackendScope()

    @contextmanager
    def changed_scope() -> Iterator[NativeEmbeddingBackend]:
        with scope() as backend:
            (tmp_path / "input.json").write_bytes(b"changed")
            yield backend

    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="INPUT_CHANGED"):
        handoff.run_native_embedding_descriptors(descriptors, changed_scope)
    assert scope.events == ["construct", "exit"]
    assert not scope.backend.calls
    assert not (tmp_path / "result.json").read_bytes()


def test_partial_os_writes_are_completed_without_second_inference(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = BackendScope()
    actual_write = os.write
    counts: list[int] = []

    def partial(descriptor: int, payload: Any) -> int:
        counts.append(descriptor)
        return actual_write(descriptor, payload[:7])

    monkeypatch.setattr(os, "write", partial)
    handoff.run_native_embedding_descriptors(descriptors, scope)
    assert len(counts) > 2 and len(scope.backend.calls) == 1
    parse_incremental_embedding_result(json.loads((tmp_path / "result.json").read_bytes()))


@pytest.mark.parametrize("stage", ["binary", "result"])
def test_failure_between_members_preserves_partial_output_and_closes_scope(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    scope = BackendScope()
    actual_write = os.write
    writes = 0

    def failed(descriptor: int, payload: Any) -> int:
        nonlocal writes
        writes += 1
        target = descriptors.vectors if stage == "binary" else descriptors.result
        if descriptor == target:
            actual_write(descriptor, payload[:7])
            raise OSError("untrusted input text must not be rendered")
        return actual_write(descriptor, payload)

    monkeypatch.setattr(os, "write", failed)
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="IO_FAILED") as failure:
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert str(failure.value) == "EMBEDDING_HANDOFF_IO_FAILED"
    assert scope.events == ["construct", "exit"] and len(scope.backend.calls) == 1
    assert writes == (1 if stage == "binary" else 2)
    assert (
        len((tmp_path / ("vectors.f32" if stage == "binary" else "result.json")).read_bytes()) == 7
    )
    if stage == "binary":
        assert not (tmp_path / "result.json").read_bytes()


def test_zero_write_is_not_retry_or_success(
    descriptors: handoff.NativeEmbeddingDescriptors, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = BackendScope()
    monkeypatch.setattr(os, "write", lambda _fd, _payload: 0)
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="WRITE_FAILED"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert len(scope.backend.calls) == 1 and scope.events[-1] == "exit"


def test_corrupt_encoded_binary_is_not_written_or_reencoded(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_encode = encode_incremental_batch

    def corrupted(request: Any, backend: NativeEmbeddingBackend) -> Any:
        batch = original_encode(request, backend)
        return replace(batch, vectors=b"x" * len(batch.vectors))

    monkeypatch.setattr(handoff, "encode_incremental_batch", corrupted)
    scope = BackendScope()
    with pytest.raises(EmbeddingVectorBinaryError, match="HASH_MISMATCH"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert len(scope.backend.calls) == 1 and not (tmp_path / "vectors.f32").read_bytes()
    assert not (tmp_path / "result.json").read_bytes()


@pytest.mark.parametrize("field", ["input", "result", "vectors"])
def test_wrong_access_flags_are_refused(
    descriptors: handoff.NativeEmbeddingDescriptors, tmp_path: Path, field: str
) -> None:
    name = {"input": "input.json", "result": "result.json", "vectors": "vectors.f32"}[field]
    alternate = os.open(tmp_path / name, os.O_RDWR)
    scope = BackendScope()
    try:
        with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
            handoff.run_native_embedding_descriptors(
                replace(descriptors, **{field: alternate}), scope
            )
    finally:
        os.close(alternate)
    assert not scope.events


@pytest.mark.parametrize("field", ["result", "vectors"])
def test_append_flag_is_refused_before_construction(
    descriptors: handoff.NativeEmbeddingDescriptors, field: str
) -> None:
    target = getattr(descriptors, field)
    fcntl.fcntl(target, fcntl.F_SETFL, fcntl.fcntl(target, fcntl.F_GETFL) | os.O_APPEND)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


@pytest.mark.parametrize("field", ["input", "result", "vectors"])
def test_multiple_links_are_refused(
    descriptors: handoff.NativeEmbeddingDescriptors, tmp_path: Path, field: str
) -> None:
    name = {"input": "input.json", "result": "result.json", "vectors": "vectors.f32"}[field]
    os.link(tmp_path / name, tmp_path / "untrusted-alias")
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


def test_input_changes_during_read_never_constructs_backend(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_read = os.read

    def changed_read(descriptor: int, amount: int) -> bytes:
        value = actual_read(descriptor, amount)
        if descriptor == descriptors.input:
            (tmp_path / "input.json").write_bytes(b"changed")
        return value

    monkeypatch.setattr(os, "read", changed_read)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="INPUT_CHANGED"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


def test_input_change_during_encoding_does_not_write_any_output(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = BackendScope()
    actual_encode = scope.backend.encode

    def changed_encode(texts: Any, *, purpose: Any) -> Any:
        result = actual_encode(texts, purpose=purpose)
        (tmp_path / "input.json").write_bytes(b"changed")
        return result

    monkeypatch.setattr(scope.backend, "encode", changed_encode)
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="INPUT_CHANGED"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert len(scope.backend.calls) == 1
    assert not (tmp_path / "result.json").read_bytes()
    assert not (tmp_path / "vectors.f32").read_bytes()


def test_binary_changes_while_result_is_written_does_not_report_success(
    descriptors: handoff.NativeEmbeddingDescriptors,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_write = os.write

    def changed_write(descriptor: int, payload: Any) -> int:
        count = actual_write(descriptor, payload)
        if descriptor == descriptors.result:
            (tmp_path / "vectors.f32").write_bytes(b"changed")
        return count

    monkeypatch.setattr(os, "write", changed_write)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="OUTPUT_CHANGED"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert len(scope.backend.calls) == 1 and scope.events[-1] == "exit"
    assert (tmp_path / "result.json").read_bytes()
    assert (tmp_path / "vectors.f32").read_bytes() == b"changed"


def test_third_party_error_is_redacted_without_retry(
    descriptors: handoff.NativeEmbeddingDescriptors, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = BackendScope()

    def failed(_texts: Any, *, purpose: Any) -> Any:
        raise ValueError("raw admitted question must not be surfaced")

    monkeypatch.setattr(scope.backend, "encode", failed)
    with pytest.raises(handoff.NativeEmbeddingHandoffError) as failure:
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert str(failure.value) == "EMBEDDING_HANDOFF_EXECUTION_FAILED"
    assert scope.events == ["construct", "exit"]


def test_scope_exit_failure_never_becomes_success(
    descriptors: handoff.NativeEmbeddingDescriptors, tmp_path: Path
) -> None:
    scope = BackendScope()

    @contextmanager
    def failed_exit() -> Iterator[NativeEmbeddingBackend]:
        with scope() as backend:
            yield backend
        raise RuntimeError("sensitive teardown details")

    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="EXECUTION_FAILED"):
        handoff.run_native_embedding_descriptors(descriptors, failed_exit)
    assert len(scope.backend.calls) == 1
    assert (tmp_path / "result.json").read_bytes()
    assert (tmp_path / "vectors.f32").read_bytes()


@pytest.mark.parametrize("drift", ["OFFSET", "APPEND_FLAG"])
def test_output_descriptor_state_drift_while_result_written_is_not_success(
    descriptors: handoff.NativeEmbeddingDescriptors,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    actual_write = os.write

    def changed_write(descriptor: int, payload: Any) -> int:
        count = actual_write(descriptor, payload)
        if descriptor == descriptors.result:
            if drift == "OFFSET":
                os.lseek(descriptors.vectors, 0, os.SEEK_SET)
            else:
                flags = fcntl.fcntl(descriptors.vectors, fcntl.F_GETFL)
                fcntl.fcntl(descriptors.vectors, fcntl.F_SETFL, flags | os.O_APPEND)
        return count

    monkeypatch.setattr(os, "write", changed_write)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="OUTPUT_CHANGED"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert len(scope.backend.calls) == 1 and scope.events[-1] == "exit"


def test_input_above_limit_never_constructs_backend(
    descriptors: handoff.NativeEmbeddingDescriptors, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handoff, "MAX_EMBEDDING_INPUT_BYTES", 10)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


def test_foreign_owner_never_constructs_backend(
    descriptors: handoff.NativeEmbeddingDescriptors, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handoff, "_ROOT_UID", os.getuid() + 1000)
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(descriptors, scope)
    assert not scope.events


@pytest.mark.parametrize("value", [True, -1, 0.5])
def test_invalid_descriptor_value_never_constructs_backend(
    descriptors: handoff.NativeEmbeddingDescriptors, value: Any
) -> None:
    scope = BackendScope()
    with pytest.raises(handoff.NativeEmbeddingHandoffError, match="DESCRIPTOR_INVALID"):
        handoff.run_native_embedding_descriptors(replace(descriptors, vectors=value), scope)
    assert not scope.events
