"""Synthetic contract metadata only: no genuine production QUERY admission or inference."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    ReferenceQuerySpaces,
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
    validate_reference_query_result,
)
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_space,
    encoding_identity,
    seal,
    vector_shard,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import sha

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def query_input_body() -> dict[str, Any]:
    query = embedding_space(purpose="QUERY")
    rows: list[dict[str, Any]] = [
        {
            "view": view,
            "encoding": encoding_identity(text, query).model_dump(mode="json"),
            "text": text,
        }
        for view, text in (
            ("CONTENT_ONLY", "주어진 전하와 힘을 비교한다."),
            ("CONCRETE_FACETS", "전하 보존과 비례 관계를 적용한다."),
        )
    ]
    rows.sort(key=lambda row: row["encoding"]["encoding_sha256"])
    return seal(
        {
            "schema_version": "embedding-reference-query-input/1.0",
            "job_id": "job_" + "a" * 32,
            "query_request_id": "embeddingquery_" + "a" * 32,
            "context_request_sha256": sha("c"),
            "spaces": {
                "query": query.model_dump(mode="json"),
                "document": embedding_space().model_dump(mode="json"),
            },
            "recipe": view_recipe().model_dump(mode="json"),
            "rows": rows,
            "batch_size": 2,
            "threads": 1,
            "input_set_sha256": embedding_input_set_sha256(
                tuple(encoding_identity(row["text"], query) for row in rows)
            ),
        },
        "request_sha256",
    )


def query_result_body(request: dict[str, Any] | None = None) -> dict[str, Any]:
    source = parse_embedding_reference_query_input(request or query_input_body())
    shard = vector_shard(tuple(row.encoding for row in source.rows), space=source.spaces.query)
    return seal(
        {
            "schema_version": "embedding-reference-query-result/1.0",
            "job_id": source.job_id,
            "query_request_id": source.query_request_id,
            "context_request_sha256": source.context_request_sha256,
            "request_sha256": source.request_sha256,
            "spaces": source.spaces.model_dump(mode="json"),
            "recipe": source.recipe.model_dump(mode="json"),
            "input_set_sha256": source.input_set_sha256,
            "shard": shard.model_dump(mode="json"),
            "view_rows": [
                {
                    "view": row.view,
                    "row_index": index,
                    "encoding_sha256": row.encoding.encoding_sha256,
                }
                for index, row in enumerate(source.rows)
            ],
        },
        "result_sha256",
    )


def test_schema_mirror_raw_hash_draft_and_closed_root() -> None:
    resource = CATALOG_SCHEMA_RESOURCES["embedding-reference-query"]
    payload = (ROOT / resource.canonical_path).read_bytes()
    mirror = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    assert payload == mirror.read_bytes()
    assert (
        sha256_bytes(payload)
        == resource.sha256
        == "sha256:51c563a0b329c3cb81ac3e2a2ca8d53db1019099c10f447c9019f770303daf44"
    )
    Draft202012Validator.check_schema(load_schema("embedding-reference-query"))


def test_genuine_purpose_closed_result_and_float_free_canonical_round_trip() -> None:
    request = parse_embedding_reference_query_input(query_input_body())
    result = parse_embedding_reference_query_result(query_result_body())
    assert request.spaces.query.purpose == "QUERY"
    assert request.spaces.document.purpose == "DOCUMENT"
    validate_reference_query_result(request, result)
    assert parse_embedding_reference_query_input(request) == request
    assert parse_embedding_reference_query_result(result) == result
    reordered = dict(reversed(tuple(result.model_dump(mode="json").items())))
    assert canonical_json_bytes(result.model_dump(mode="json")) == canonical_json_bytes(
        parse_embedding_reference_query_result(reordered).model_dump(mode="json")
    )
    assert REFERENCE_QUERY_RESULT_REF.endswith("/1.0")


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "ADMIN"),
        ("authority", "WORKER"),
        ("workspace", "/mnt/nas"),
        ("approved", True),
        ("batch_size", True),
        ("threads", 1.0),
        ("schema_version", "incremental-embedding-input/1.0"),
    ],
)
def test_query_rejects_authority_paths_extra_or_coercion(field: str, value: object) -> None:
    document = query_input_body()
    document[field] = value
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input(
            document if isinstance(value, float) else seal(document, "request_sha256")
        )


@pytest.mark.parametrize(
    "change",
    [
        "DOCUMENT",
        "device",
        "runtime",
        "model",
        "normalization",
        "recipe",
        "text_hash",
        "duplicate_view",
        "input_set",
        "missing",
    ],
)
def test_query_rejects_wrong_purpose_pair_recipe_or_row_closure(change: str) -> None:
    document = query_input_body()
    if change == "DOCUMENT":
        document["spaces"]["query"] = embedding_space().model_dump(mode="json")
    elif change == "device":
        document["spaces"]["document"] = embedding_space(device="CUDA").model_dump(mode="json")
    elif change == "runtime":
        document["spaces"]["document"] = embedding_space(fingerprint=sha("b")).model_dump(
            mode="json"
        )
    elif change == "model":
        document["spaces"]["document"]["model_spec"]["model_revision_id"] = (
            "embeddingmodelrev_" + "f" * 32
        )
    elif change == "normalization":
        document["spaces"]["query"]["model_spec"]["normalization"] = "NONE"
    elif change == "recipe":
        document["recipe"]["recipe_sha256"] = sha("b")
    elif change == "text_hash":
        document["rows"][0]["text"] += " 아니다."
    elif change == "duplicate_view":
        document["rows"][1]["view"] = document["rows"][0]["view"]
    elif change == "input_set":
        document["input_set_sha256"] = sha("b")
    else:
        document.pop("query_request_id")
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input(seal(document, "request_sha256"))


@pytest.mark.parametrize("change", ["request", "view", "row", "space", "result_hash", "input_set"])
def test_query_result_rejects_wrong_pinned_execution_or_row(change: str) -> None:
    document = query_result_body()
    if change == "request":
        document["query_request_id"] = "embeddingquery_" + "b" * 32
    elif change == "view":
        document["view_rows"][0]["view"] = "METADATA_ONLY"
    elif change == "row":
        document["view_rows"][0]["row_index"] = 2
    elif change == "space":
        document["spaces"]["query"] = embedding_space(purpose="QUERY", device="CUDA").model_dump(
            mode="json"
        )
    elif change == "result_hash":
        document["result_sha256"] = sha("b")
    else:
        document["input_set_sha256"] = sha("b")
    if change != "result_hash":
        document = seal(document, "result_sha256")
    with pytest.raises(ERRORS):
        validate_reference_query_result(
            parse_embedding_reference_query_input(query_input_body()),
            parse_embedding_reference_query_result(document),
        )


def test_nested_model_copy_construct_boolean_and_extra_values_are_not_repaired() -> None:
    request = parse_embedding_reference_query_input(query_input_body())
    for copied in (
        request.model_copy(update={"threads": True}),
        request.model_copy(update={"authority": "ADMIN"}),
        request.model_copy(
            update={"recipe": request.recipe.model_copy(update={"maximum_text_bytes": True})}
        ),
        request.model_copy(
            update={
                "rows": (
                    request.rows[0].model_copy(update={"text": "다른 조건"}),
                    *request.rows[1:],
                )
            }
        ),
        request.model_copy(
            update={"spaces": request.spaces.model_copy(update={"document": request.spaces.query})}
        ),
    ):
        with pytest.raises(ERRORS):
            parse_embedding_reference_query_input(copied)
    with pytest.raises(ValueError):
        ReferenceQuerySpaces.model_validate(
            request.spaces.model_copy(update={"authority": "ADMIN"})
        )
    assert request == parse_embedding_reference_query_input(query_input_body())


def test_float_payload_cannot_relax_canonical_json() -> None:
    document = copy.deepcopy(query_input_body())
    document["rows"][0]["vector"] = [0.1]
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input(document)
