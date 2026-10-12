"""Synthetic native backend tests; not real CPU/CUDA inference or runtime admission."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingExecutionRuntime,
    EmbeddingSpace,
    parse_embedding_shard,
    validate_incremental_embedding_result,
)
from eom_catalog_service.embedding_encoder_adapter import (
    IncrementalEmbeddingEncodeError,
    encode_incremental_batch,
)
from eom_catalog_service.inference_transfer_ports import EmbeddingRankerProvenance
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_input,
    embedding_space,
    execution_runtime,
    seal,
)


class SyntheticNativeBackend:
    def __init__(self, space: EmbeddingSpace) -> None:
        self.batch_size = 2
        self.threads = 1
        self.dimension: int = space.model_spec.dimension
        self.provenance = EmbeddingRankerProvenance("PINNED_MODEL", space.model_spec)
        self.execution_runtime: EmbeddingExecutionRuntime = space.runtime
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.output: tuple[tuple[float, ...], ...] | None = None
        self.changed_runtime: EmbeddingExecutionRuntime | None = None

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append((texts, purpose))
        if self.changed_runtime is not None:
            self.execution_runtime = self.changed_runtime
        if self.output is not None:
            return self.output
        return tuple(
            tuple(1.0 if column == row else 0.0 for column in range(self.dimension))
            for row in range(len(texts))
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("batch_size", True),
        ("batch_size", 3),
        ("batch_size", 2.0),
        ("threads", True),
        ("threads", 2),
        ("threads", 1.0),
    ],
)
@pytest.mark.parametrize("stage", ["BEFORE", "AFTER"])
def test_exact_batch_and_thread_recipe_checked_before_and_after_encoding(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any, stage: str
) -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    if stage == "BEFORE":
        setattr(backend, field, value)
    else:
        original_encode = backend.encode

        def changed_recipe(
            texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
        ) -> tuple[tuple[float, ...], ...]:
            vectors = original_encode(texts, purpose=purpose)
            setattr(backend, field, value)
            return vectors

        monkeypatch.setattr(backend, "encode", changed_recipe)
    with pytest.raises(IncrementalEmbeddingEncodeError, match="RECIPE_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert len(backend.calls) == (0 if stage == "BEFORE" else 1)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_exact_native_input_builds_binary_shard_and_closed_result(
    device: Literal["CPU", "CUDA"],
) -> None:
    request = embedding_input(
        "속력이 10 m/s이다.",
        "마찰이 없으며 에너지는 보존된다.",
        space=embedding_space(device=device),
    )
    backend = SyntheticNativeBackend(request.space)
    encoded = encode_incremental_batch(request, backend)
    assert backend.calls == [(tuple(row.text for row in request.rows), "DOCUMENT")]
    validate_incremental_embedding_result(request, encoded.result)
    shard = parse_embedding_shard(encoded.result.shard.model_dump(mode="json"))
    rows = read_unit_vectors(
        encoded.vectors,
        dimension=shard.dimension,
        row_count=shard.row_count,
        expected_sha256=shard.binary.sha256,
    )
    assert tuple(row.encoding for row in request.rows) == shard.rows
    assert rows[0][0] == 1.0 and rows[1][1] == 1.0
    assert shard.binary.sha256 == sha256_bytes(encoded.vectors)
    metadata = canonical_json_bytes(encoded.result.model_dump(mode="json"))
    assert b"vectors.f32" in metadata
    assert encoded.vectors not in metadata
    assert shard.space.runtime.device == device


def test_source_text_negation_units_and_order_are_not_rewritten() -> None:
    request = embedding_input("질량이 2 kg이고 마찰은 없다.", "전하량은 -3 C이다.")
    backend = SyntheticNativeBackend(request.space)
    encode_incremental_batch(request, backend)
    assert backend.calls[0] == (tuple(row.text for row in request.rows), "DOCUMENT")
    assert all(row.encoding.input_text_sha256 == content_sha256(row.text) for row in request.rows)


def test_canonical_json_member_and_semantic_manifest_hash_are_distinct() -> None:
    request = embedding_input()
    batch = encode_incremental_batch(request, SyntheticNativeBackend(request.space))
    shard = batch.result.shard
    json_member = canonical_json_bytes(shard.model_dump(mode="json"))
    assert sha256_bytes(json_member) == content_sha256(shard.model_dump(mode="json"))
    assert sha256_bytes(json_member) != shard.shard_sha256
    assert sha256_bytes(json_member) != shard.binary.sha256


def test_model_mismatch_is_rejected_before_any_encode() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    backend.dimension += 1
    with pytest.raises(IncrementalEmbeddingEncodeError, match="MODEL_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert backend.calls == []


def test_test_only_backend_cannot_publish_as_a_pinned_model() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    backend.provenance = EmbeddingRankerProvenance("TEST_ONLY", None)
    with pytest.raises(IncrementalEmbeddingEncodeError, match="MODEL_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert backend.calls == []


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_device_mismatch_never_falls_back_or_runs_a_substitute_backend(
    device: Literal["CPU", "CUDA"],
) -> None:
    request = embedding_input(space=embedding_space(device=device))
    other: Literal["CPU", "CUDA"] = "CUDA" if device == "CPU" else "CPU"
    backend = SyntheticNativeBackend(request.space)
    backend.execution_runtime = execution_runtime(other)
    with pytest.raises(IncrementalEmbeddingEncodeError, match="RUNTIME_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert backend.calls == []


def test_changed_runtime_fingerprint_before_encode_fails_closed() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    backend.execution_runtime = execution_runtime(fingerprint="sha256:" + "f" * 64)
    with pytest.raises(IncrementalEmbeddingEncodeError, match="RUNTIME_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert backend.calls == []


def test_changed_runtime_during_encode_discards_result_without_second_inference() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    backend.changed_runtime = execution_runtime("CUDA")
    with pytest.raises(IncrementalEmbeddingEncodeError, match="RUNTIME_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert len(backend.calls) == 1


@pytest.mark.parametrize("count", [0, 2])
def test_result_row_count_is_not_padded_or_retried(count: int) -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    vector = (1.0,) + (0.0,) * (backend.dimension - 1)
    backend.output = (vector,) * count
    with pytest.raises(IncrementalEmbeddingEncodeError, match="ROW_COUNT_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert len(backend.calls) == 1


def test_nonunit_backend_output_is_rejected_not_repaired() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    backend.output = ((2.0,) + (0.0,) * (backend.dimension - 1),)
    with pytest.raises(EmbeddingVectorBinaryError, match="NORM_INVALID"):
        encode_incremental_batch(request, backend)
    assert len(backend.calls) == 1


def test_construct_bypass_with_modified_request_hash_is_rejected_before_encode() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    corrupted = request.model_copy(update={"request_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="request_sha256"):
        encode_incremental_batch(corrupted, backend)
    assert backend.calls == []


def test_rehashed_modified_text_still_requires_exact_encoding_identity() -> None:
    request = embedding_input()
    backend = SyntheticNativeBackend(request.space)
    body = request.model_dump(mode="json")
    body["rows"][0]["text"] = "조건을 지워서 바꾼 문장이다."
    corrupted = request.model_copy(
        update={
            "rows": (request.rows[0].model_copy(update={"text": body["rows"][0]["text"]}),),
            "request_sha256": seal(body, "request_sha256")["request_sha256"],
        }
    )
    with pytest.raises(ValueError, match="input text hash"):
        encode_incremental_batch(corrupted, backend)
    assert backend.calls == []


def test_encoder_adapter_and_ports_do_not_import_database_filesystem_or_torch() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("embedding_encoder_adapter.py", "embedding_execution_ports.py"):
        tree = ast.parse((root / "services/catalog_service/eom_catalog_service" / name).read_text())
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            item.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for item in node.names
        )
        assert not imports & {"torch", "sqlalchemy", "os", "pathlib", "subprocess", "httpx"}
