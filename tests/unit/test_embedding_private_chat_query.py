"""Private questions use a distinct protocol and the shared numerical implementation."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import parse_embedding_reference_query_result
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_supported_reference_query_input,
)
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.similarity_context import SimilarityViewSelection
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.embedding_encoder_adapter import (
    PrivateChatQueryEmbeddingEncodeError,
    encode_private_chat_query,
)
from eom_catalog_service.embedding_native_stdio import (
    NativeEmbeddingDescriptors,
    NativeEmbeddingHandoffError,
    run_native_private_chat_query_descriptors,
    run_native_reference_query_descriptors,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.general_chat_similarity_basis import (
    PreparedPrivateChatQuery,
    build_private_chat_query_encoding_input,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import execution_runtime, seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_private_chat_query_basis import TEXT, basis
from tests.unit.test_similarity_context_contracts import context_request_body


def selection():
    return SimilarityViewSelection.model_validate(context_request_body()["views"][0])


def request_body():
    return build_private_chat_query_encoding_input(
        PreparedPrivateChatQuery(basis(), TEXT),
        selection(),
        context_request_sha256="sha256:" + "6" * 64,
        job_id="job_" + "7" * 32,
        query_request_id="embeddingquery_" + "8" * 32,
        batch_size=4,
        threads=1,
    ).model_dump(mode="json")


def backend(request):
    value = SyntheticNativeBackend(request.spaces.query)
    value.batch_size, value.threads = request.batch_size, request.threads
    return value


def test_schema_mirror_pins_are_exact_and_no_predecessor_is_relabelled():
    resource = CATALOG_SCHEMA_RESOURCES["embedding-private-chat-query"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert (
        sha256_bytes(raw)
        == resource.sha256
        == ("sha256:50feda7efee0617663def17ab3684afba2580769c1a6454518d042520f75b75b")
    )
    Draft202012Validator.check_schema(load_schema("embedding-private-chat-query"))
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    result = encode_private_chat_query(request, backend(request)).result
    for reader, value in (
        (parse_supported_reference_query_input, request),
        (parse_embedding_reference_query_result, result),
    ):
        with pytest.raises((ValueError, SchemaError)):
            reader(value)


def test_exact_owned_question_is_one_query_not_a_document_or_solution_report():
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    value = backend(request)
    output = encode_private_chat_query(request, value)
    validate_private_chat_query_result(request, output.result)
    assert value.calls == [((TEXT,), "QUERY")]
    assert request.row.view == "CONTENT_ONLY" and request.batch_size == 4
    assert request.basis.query_text_sha256 == sha256_bytes(TEXT.encode())
    assert request.row.encoding.input_text_sha256 == content_sha256(TEXT)
    assert request.row.encoding.input_text_sha256 != request.basis.query_text_sha256
    assert output.result.basis_sha256 == request.basis.basis_sha256
    assert output.result.shard.rows == (request.row.encoding,)
    assert output.result.shard.space == request.spaces.query
    assert len(output.vectors) == request.spaces.query.model_spec.dimension * 4
    assert output == encode_private_chat_query(request, backend(request))
    assert TEXT not in canonical_json_bytes(output.result).decode()
    read_unit_vectors(
        output.vectors,
        dimension=value.dimension,
        row_count=1,
        expected_sha256=output.result.shard.binary.sha256,
    )
    with pytest.raises(FrozenInstanceError):
        output.vectors = b"changed"


@pytest.mark.parametrize(
    "fault",
    [
        "text",
        "basis",
        "space",
        "view",
        "set_hash",
        "input_hash",
        "boolean_batch",
        "extra",
        "copied",
    ],
)
def test_invalid_or_cross_bound_input_fails_before_encode(fault):
    body = request_body()
    if fault == "text":
        body["row"]["text"] += " altered"
    elif fault == "basis":
        body["basis"]["query_text_sha256"] = "sha256:" + "9" * 64
        body["basis"] = seal(body["basis"], "basis_sha256")
    elif fault == "space":
        body["row"]["encoding"]["space_sha256"] = body["spaces"]["document"]["space_sha256"]
        body["row"]["encoding"] = seal(body["row"]["encoding"], "encoding_sha256")
    elif fault == "view":
        body["row"]["view"] = "CONCRETE_FACETS"
    elif fault == "set_hash":
        body["input_set_sha256"] = "sha256:" + "9" * 64
    elif fault == "input_hash":
        body["batch_size"] = 3
    elif fault == "boolean_batch":
        body["batch_size"] = True
    elif fault == "extra":
        body["actor_id"] = "ADMIN"
    else:
        value = EmbeddingPrivateChatQueryInput.model_validate(body)
        body = value.model_copy(
            update={"basis": value.basis.model_copy(update={"authority": "ADMIN"})}
        )
    if fault not in {"input_hash", "copied"}:
        body = seal(body, "request_sha256")
    with pytest.raises((ValueError, SchemaError)):
        EmbeddingPrivateChatQueryInput.model_validate(body)


@pytest.mark.parametrize(
    "field",
    [
        "job_id",
        "query_request_id",
        "context_request_sha256",
        "basis_sha256",
        "request_sha256",
        "input_set_sha256",
    ],
)
def test_foreign_result_cannot_attach_to_the_original_private_question(field):
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    result = encode_private_chat_query(request, backend(request)).result
    body = result.model_dump(mode="json")
    body[field] = (
        "job_"
        if field == "job_id"
        else "embeddingquery_"
        if field == "query_request_id"
        else "sha256:"
    ) + "9" * (32 if field in {"job_id", "query_request_id"} else 64)
    with pytest.raises((ValueError, SchemaError)):
        other = EmbeddingPrivateChatQueryResult.model_validate(seal(body, "result_sha256"))
        validate_private_chat_query_result(request, other)


@pytest.mark.parametrize("stage", ["BEFORE", "AFTER"])
@pytest.mark.parametrize("fault", ["runtime", "dimension", "batch", "boolean_threads"])
def test_backend_runtime_and_recipe_are_checked_before_and_after_one_call(
    monkeypatch, stage, fault
):
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    value = backend(request)

    def change():
        if fault == "runtime":
            value.execution_runtime = execution_runtime("CUDA")
        elif fault == "dimension":
            value.dimension += 1
        elif fault == "batch":
            value.batch_size = 1
        else:
            value.threads = True

    if stage == "BEFORE":
        change()
    else:
        original = value.encode

        def changed(*args, **kwargs):
            vectors = original(*args, **kwargs)
            change()
            return vectors

        monkeypatch.setattr(value, "encode", changed)
    with pytest.raises(PrivateChatQueryEmbeddingEncodeError, match="MISMATCH"):
        encode_private_chat_query(request, value)
    assert len(value.calls) == (0 if stage == "BEFORE" else 1)


@pytest.mark.parametrize("fault", ["count", "dimension", "nan", "norm", "diagnostics"])
def test_bad_vectors_or_backend_errors_do_not_become_a_result_or_leak_text(monkeypatch, fault):
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    value = backend(request)
    if fault == "diagnostics":

        def failed(*args, **kwargs):
            raise RuntimeError("private prompt: " + TEXT)

        monkeypatch.setattr(value, "encode", failed)
    else:
        vector = [0.0] * value.dimension
        vector[0] = float("nan") if fault == "nan" else 2.0 if fault == "norm" else 1.0
        if fault == "dimension":
            vector.pop()
        value.output = () if fault == "count" else (tuple(vector),)
    with pytest.raises((PrivateChatQueryEmbeddingEncodeError, EmbeddingVectorBinaryError)) as error:
        encode_private_chat_query(request, value)
    assert TEXT not in str(error.value)


@pytest.mark.parametrize("fault", ["index_absent", "view", "changed_text"])
def test_owner_projection_rejects_absent_or_inapplicable_selection(fault):
    prepared, selected = PreparedPrivateChatQuery(basis(), TEXT), selection()
    if fault == "index_absent":
        selected = selected.model_copy(update={"index": None})
    elif fault == "view":
        selected = selected.model_copy(update={"view": "METADATA_ONLY"})
    else:
        object.__setattr__(prepared, "text", TEXT + " changed")
    with pytest.raises(ValueError):
        build_private_chat_query_encoding_input(
            prepared,
            selected,
            context_request_sha256="sha256:" + "6" * 64,
            job_id="job_" + "7" * 32,
            query_request_id="embeddingquery_" + "8" * 32,
            batch_size=4,
            threads=1,
        )


def test_old_native_query_entry_refuses_private_schema_before_constructing_backend(
    tmp_path, monkeypatch
):
    from eom_catalog_service import embedding_native_stdio

    monkeypatch.setattr(embedding_native_stdio, "_ROOT_UID", os.getuid())
    path = tmp_path / "input.json"
    path.write_bytes(canonical_json_bytes(request_body()))
    path.chmod(0o600)
    source = os.open(path, os.O_RDONLY)
    outputs = [
        os.open(tmp_path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        for name in ("result.json", "vectors.f32")
    ]
    for fd in outputs:
        os.fchmod(fd, 0o640)
    constructed = []

    @contextmanager
    def scope():
        constructed.append(True)
        yield None

    try:
        with pytest.raises(NativeEmbeddingHandoffError):
            run_native_reference_query_descriptors(
                NativeEmbeddingDescriptors(source, *outputs), scope
            )
        assert constructed == []
        assert all(os.fstat(fd).st_size == 0 for fd in outputs)
    finally:
        for fd in (source, *outputs):
            os.close(fd)


@pytest.fixture
def private_descriptors(tmp_path, monkeypatch):
    from eom_catalog_service import embedding_native_stdio

    monkeypatch.setattr(embedding_native_stdio, "_ROOT_UID", os.getuid())
    path = tmp_path / "input.json"
    path.write_bytes(canonical_json_bytes(request_body()))
    path.chmod(0o600)
    source = os.open(path, os.O_RDONLY)
    outputs = [
        os.open(tmp_path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        for name in ("result.json", "vectors.f32")
    ]
    for fd in outputs:
        os.fchmod(fd, 0o640)
    try:
        yield NativeEmbeddingDescriptors(source, *outputs)
    finally:
        for fd in (source, *outputs):
            os.close(fd)


def test_private_descriptor_pipeline_writes_binary_then_exact_private_result(
    private_descriptors, tmp_path, monkeypatch
):
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    value = backend(request)
    syncs = []
    real_fsync = os.fsync

    def fsync(fd):
        syncs.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    @contextmanager
    def scope():
        yield value

    run_native_private_chat_query_descriptors(private_descriptors, scope)
    raw = (tmp_path / "result.json").read_bytes()
    result = EmbeddingPrivateChatQueryResult.model_validate(json.loads(raw))
    validate_private_chat_query_result(request, result)
    assert canonical_json_bytes(result) == raw
    assert syncs == [private_descriptors.vectors, private_descriptors.result]
    assert value.calls == [((TEXT,), "QUERY")]
    binary = (tmp_path / "vectors.f32").read_bytes()
    assert len(binary) == request.spaces.query.model_spec.dimension * 4
    read_unit_vectors(
        binary, dimension=value.dimension, row_count=1, expected_sha256=result.shard.binary.sha256
    )
    assert not (tmp_path / "shard.json").exists()


@pytest.mark.parametrize(
    "fault", ["reference", "noncanonical", "duplicate", "nonempty", "append", "alias"]
)
def test_private_handoff_failures_precede_backend_construction(
    private_descriptors, tmp_path, fault
):
    from tests.unit.test_embedding_reference_query_v11_contracts import input_body

    if fault == "reference":
        (tmp_path / "input.json").write_bytes(canonical_json_bytes(input_body()))
    elif fault == "noncanonical":
        (tmp_path / "input.json").write_bytes(canonical_json_bytes(request_body()) + b"\n")
    elif fault == "duplicate":
        raw = canonical_json_bytes(request_body())
        (tmp_path / "input.json").write_bytes(b'{"job_id":"job_' + b"a" * 32 + b'",' + raw[1:])
    elif fault == "nonempty":
        os.write(private_descriptors.result, b"existing")
    elif fault == "append":
        fcntl.fcntl(
            private_descriptors.result,
            fcntl.F_SETFL,
            fcntl.fcntl(private_descriptors.result, fcntl.F_GETFL) | os.O_APPEND,
        )
    else:
        private_descriptors = NativeEmbeddingDescriptors(
            private_descriptors.input, private_descriptors.result, private_descriptors.result
        )
    constructed = []

    @contextmanager
    def scope():
        constructed.append(True)
        yield None

    with pytest.raises(NativeEmbeddingHandoffError):
        run_native_private_chat_query_descriptors(private_descriptors, scope)
    assert constructed == []


def test_private_input_mutation_during_encode_keeps_outputs_empty(
    private_descriptors, tmp_path, monkeypatch
):
    request = EmbeddingPrivateChatQueryInput.model_validate(request_body())
    value = backend(request)
    original = value.encode

    def changed(*args, **kwargs):
        vectors = original(*args, **kwargs)
        (tmp_path / "input.json").write_bytes(b"changed while encoding")
        return vectors

    monkeypatch.setattr(value, "encode", changed)

    @contextmanager
    def scope():
        yield value

    with pytest.raises(NativeEmbeddingHandoffError, match="INPUT_CHANGED"):
        run_native_private_chat_query_descriptors(private_descriptors, scope)
    assert value.calls == [((TEXT,), "QUERY")]
    assert all(
        os.fstat(fd).st_size == 0
        for fd in (private_descriptors.result, private_descriptors.vectors)
    )
