"""Synthetic input/closure tests only; no model, QUERY launch, or authority admission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import (
    REFERENCE_QUERY_INPUT_V11_REF,
    REFERENCE_QUERY_INPUT_V11_SCHEMA,
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_INPUT_REF,
    REFERENCE_QUERY_RESULT_REF,
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
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
from tests.unit.inference_transfer_fixtures import embedding_model, sha
from tests.unit.test_embedding_reference_query_contracts import query_input_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def input_body(*, batch_size: int = 4, row_count: int = 1) -> dict[str, Any]:
    query = embedding_space(purpose="QUERY")
    rows: list[dict[str, Any]] = [
        {
            "view": view,
            "encoding": encoding_identity(text, query).model_dump(mode="json"),
            "text": text,
        }
        for view, text in (
            ("CONTENT_ONLY", "두 물체의 전하와 힘을 비교한다."),
            ("METADATA_ONLY", "전하 보존과 비례 관계."),
            ("CONCRETE_FACETS", "전하 보존을 적용하여 힘의 비를 계산한다."),
        )[:row_count]
    ]
    rows.sort(key=lambda row: row["encoding"]["encoding_sha256"])
    return seal(
        {
            "schema_version": "embedding-reference-query-input/1.1",
            "job_id": "job_" + "a" * 32,
            "query_request_id": "embeddingquery_" + "a" * 32,
            "context_request_sha256": sha("c"),
            "spaces": {
                "query": query.model_dump(mode="json"),
                "document": embedding_space().model_dump(mode="json"),
            },
            "recipe": view_recipe().model_dump(mode="json"),
            "rows": rows,
            "batch_size": batch_size,
            "threads": 1,
            "input_set_sha256": embedding_input_set_sha256(
                tuple(encoding_identity(row["text"], query) for row in rows)
            ),
        },
        "request_sha256",
    )


def result_body(request: EmbeddingReferenceQueryInputV11) -> dict[str, Any]:
    shard = vector_shard(tuple(row.encoding for row in request.rows), space=request.spaces.query)
    return seal(
        {
            "schema_version": "embedding-reference-query-result/1.0",
            "job_id": request.job_id,
            "query_request_id": request.query_request_id,
            "context_request_sha256": request.context_request_sha256,
            "request_sha256": request.request_sha256,
            "spaces": request.spaces.model_dump(mode="json"),
            "recipe": request.recipe.model_dump(mode="json"),
            "input_set_sha256": request.input_set_sha256,
            "shard": shard.model_dump(mode="json"),
            "view_rows": [
                {
                    "view": row.view,
                    "row_index": index,
                    "encoding_sha256": row.encoding.encoding_sha256,
                }
                for index, row in enumerate(request.rows)
            ],
        },
        "result_sha256",
    )


def test_new_resource_raw_mirror_draft_closed_shape_and_literal_public_export() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[REFERENCE_QUERY_INPUT_V11_SCHEMA]
    assert resource.schema_version == "1.1"
    assert resource.canonical_path == (
        "schemas/knowledge/embedding-reference-query-input-v1_1.schema.json"
    )
    assert resource.resource_path == (
        "resources/knowledge/embedding-reference-query-input-v1_1.schema.json"
    )
    payload = (ROOT / resource.canonical_path).read_bytes()
    mirror = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    assert payload == mirror.read_bytes()
    assert (
        sha256_bytes(payload)
        == resource.sha256
        == "sha256:03a2d1332fefef201d30baae59597dda49a46f5650c45bf1384cf20a1f08c81d"
    )
    schema = load_schema(REFERENCE_QUERY_INPUT_V11_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == REFERENCE_QUERY_INPUT_V11_REF
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["rows"]["maxItems"] == 3
    assert schema["properties"]["batch_size"]["maximum"] == 16
    assert schema["properties"]["spaces"]["$ref"].endswith("/1.0#/$defs/spaces")
    assert schema["properties"]["rows"]["items"]["$ref"].endswith("/1.0#/$defs/inputRow")


def test_predecessors_keep_raw_bytes_metadata_and_literal_parser_meaning() -> None:
    for name, expected in (
        (
            "embedding-reference-query",
            "sha256:51c563a0b329c3cb81ac3e2a2ca8d53db1019099c10f447c9019f770303daf44",
        ),
        (
            "system-rag-similarity-context",
            "sha256:7d1d4bb07964060143acacb32a3dad8ccbc41519d5847742ffe5deb739b57b20",
        ),
    ):
        resource = CATALOG_SCHEMA_RESOURCES[name]
        assert resource.schema_version == "1.0"
        payload = (ROOT / resource.canonical_path).read_bytes()
        mirror = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        assert payload == mirror.read_bytes()
        assert sha256_bytes(payload) == resource.sha256 == expected
    old = parse_embedding_reference_query_input(query_input_body())
    assert old.schema_version == "embedding-reference-query-input/1.0"
    assert REFERENCE_QUERY_INPUT_REF.endswith("/1.0")
    assert REFERENCE_QUERY_RESULT_REF.endswith("/1.0")
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input(input_body())
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input_v11(old)
    legacy_batch_four = old.model_dump(mode="json") | {"batch_size": 4}
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input(seal(legacy_batch_four, "request_sha256"))


@pytest.mark.parametrize("batch_size", [1, 3, 4, 16])
@pytest.mark.parametrize("row_count", [1, 2, 3])
def test_configured_batch_is_not_partial_row_count(batch_size: int, row_count: int) -> None:
    request = parse_embedding_reference_query_input_v11(
        input_body(batch_size=batch_size, row_count=row_count)
    )
    assert request.batch_size == batch_size
    assert len(request.rows) == row_count
    assert request.spaces.query.purpose == "QUERY"
    assert request.spaces.document.purpose == "DOCUMENT"
    assert request.spaces.query.runtime == request.spaces.document.runtime
    assert request.spaces.query.model_spec == request.spaces.document.model_spec
    result = parse_embedding_reference_query_result(result_body(request))
    validate_reference_query_result_v11(request, result)
    assert result.schema_version == "embedding-reference-query-result/1.0"
    assert result.shard.row_count == row_count
    assert result.request_sha256 == request.request_sha256


def test_canonical_hash_round_trip_and_immutable_input() -> None:
    document = input_body(row_count=3)
    request = parse_embedding_reference_query_input_v11(document)
    reversed_keys = dict(reversed(tuple(document.items())))
    reparsed = parse_embedding_reference_query_input_v11(reversed_keys)
    assert request == reparsed == parse_embedding_reference_query_input_v11(request)
    assert canonical_json_bytes(request.model_dump(mode="json")) == canonical_json_bytes(
        reparsed.model_dump(mode="json")
    )
    assert request.request_sha256 == seal(document, "request_sha256")["request_sha256"]
    with pytest.raises(ValueError):
        request.batch_size = 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "ADMIN"),
        ("authority", "WORKER"),
        ("query_scope", {"approved": True}),
        ("source_path", "/mnt/nas/source.pdf"),
        ("workspace", "/tmp/query"),
        ("provider_capture", {"current": True}),
        ("approved", True),
        ("batch_size", True),
        ("batch_size", 0),
        ("batch_size", 17),
        ("threads", False),
        ("threads", 17),
        ("schema_version", "embedding-reference-query-input/1.0"),
        ("schema_version", "incremental-embedding-input/1.0"),
        ("job_id", "job_missing"),
        ("query_request_id", "embeddingquery_missing"),
    ],
)
def test_closed_schema_and_raw_model_reject_authority_paths_or_scalar_coercion(
    field: str, value: object
) -> None:
    document = seal(input_body() | {field: value}, "request_sha256")
    with pytest.raises(SchemaError):
        validate_contract(REFERENCE_QUERY_INPUT_V11_SCHEMA, document)
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input_v11(document)


@pytest.mark.parametrize("field", ["batch_size", "threads"])
def test_float_recipe_values_are_rejected_before_coercion(field: str) -> None:
    document = input_body()
    document[field] = 4.0
    with pytest.raises(ValueError, match="floats"):
        parse_embedding_reference_query_input_v11(document)


@pytest.mark.parametrize(
    "change",
    [
        "document_as_query",
        "device",
        "runtime",
        "model",
        "normalization",
        "recipe_hash",
        "text_hash",
        "encoding_hash",
        "duplicate_view",
        "duplicate_encoding",
        "partition",
        "row_space",
        "input_set_hash",
        "request_hash",
        "missing",
        "extra_row",
        "row_order",
        "nested_extra",
    ],
)
def test_wrong_pair_recipe_row_or_hash_is_not_repaired(change: str) -> None:
    document = input_body(row_count=3)
    if change == "document_as_query":
        document["spaces"]["query"] = embedding_space().model_dump(mode="json")
    elif change == "device":
        document["spaces"]["document"] = embedding_space(device="CUDA").model_dump(mode="json")
    elif change == "runtime":
        document["spaces"]["document"] = embedding_space(fingerprint=sha("b")).model_dump(
            mode="json"
        )
    elif change == "model":
        document["spaces"]["document"]["model_spec"] = embedding_model(
            "intfloat/multilingual-e5-base"
        ).model_dump(mode="json")
        document["spaces"]["document"] = seal(document["spaces"]["document"], "space_sha256")
    elif change == "normalization":
        document["spaces"]["query"]["model_spec"]["normalization"] = "NONE"
    elif change == "recipe_hash":
        document["recipe"]["recipe_sha256"] = sha("b")
    elif change == "text_hash":
        document["rows"][0]["text"] += " 다르다."
    elif change == "encoding_hash":
        document["rows"][0]["encoding"]["encoding_sha256"] = sha("b")
    elif change == "duplicate_view":
        document["rows"][1]["view"] = document["rows"][0]["view"]
    elif change == "duplicate_encoding":
        document["rows"][1]["encoding"] = document["rows"][0]["encoding"]
    elif change == "partition":
        row = document["rows"][0]
        row["encoding"] = encoding_identity(
            row["text"], embedding_space(purpose="QUERY"), storage_partition="other-partition"
        ).model_dump(mode="json")
    elif change == "row_space":
        row = document["rows"][0]
        row["encoding"] = encoding_identity(row["text"], embedding_space()).model_dump(mode="json")
    elif change == "input_set_hash":
        document["input_set_sha256"] = sha("b")
    elif change == "request_hash":
        document["request_sha256"] = sha("b")
    elif change == "missing":
        document.pop("query_request_id")
    elif change == "extra_row":
        document["rows"].append(document["rows"][0])
    elif change == "row_order":
        document["rows"].reverse()
    else:
        document["spaces"]["query"]["role"] = "WORKER"
    if change != "request_hash":
        document = seal(document, "request_sha256")
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input_v11(document)


@pytest.mark.parametrize("change", ["job", "query_id", "context", "request", "input_set", "view"])
def test_result_v1_requires_exact_v11_request_closure(change: str) -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    document = result_body(request)
    if change == "job":
        document["job_id"] = "job_" + "b" * 32
    elif change == "query_id":
        document["query_request_id"] = "embeddingquery_" + "b" * 32
    elif change == "context":
        document["context_request_sha256"] = sha("b")
    elif change == "request":
        document["request_sha256"] = sha("b")
    elif change == "input_set":
        document["input_set_sha256"] = sha("b")
    else:
        document["view_rows"][0]["view"] = "METADATA_ONLY"
    document = seal(document, "result_sha256")
    with pytest.raises(ERRORS):
        validate_reference_query_result_v11(
            request, parse_embedding_reference_query_result(document)
        )


@pytest.mark.parametrize("change", ["path", "schema", "dtype", "row_index", "hash"])
def test_released_result_rejects_member_row_or_hash_drift(change: str) -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    document = result_body(request)
    if change == "path":
        document["shard"]["binary"]["member_path"] = "/tmp/vectors.f32"
    elif change == "schema":
        document["shard"]["binary"]["schema_ref"] = "eom://schemas/unknown/1.0"
    elif change == "dtype":
        document["shard"]["binary"]["dtype"] = "FLOAT64"
    elif change == "row_index":
        document["view_rows"][0]["row_index"] = True
    else:
        document["result_sha256"] = sha("b")
    if change != "hash":
        document["shard"] = seal(document["shard"], "shard_sha256")
        document = seal(document, "result_sha256")
    with pytest.raises(ERRORS):
        validate_reference_query_result_v11(
            request, parse_embedding_reference_query_result(document)
        )


def test_model_copy_construct_and_nested_raw_values_are_revalidated() -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    for copied in (
        request.model_copy(update={"batch_size": True}),
        request.model_copy(update={"authority": "ADMIN"}),
        request.model_copy(update={"spaces": "bad"}),
        request.model_copy(
            update={"recipe": request.recipe.model_copy(update={"maximum_text_bytes": True})}
        ),
        request.model_copy(
            update={"rows": (request.rows[0].model_copy(update={"text": "다른 조건"}),)}
        ),
        request.model_copy(
            update={"spaces": request.spaces.model_copy(update={"query": request.spaces.document})}
        ),
        EmbeddingReferenceQueryInputV11.model_construct(**(input_body() | {"batch_size": True})),
        EmbeddingReferenceQueryInputV11.model_construct(job_id=request.job_id),
    ):
        with pytest.raises(ERRORS):
            parse_embedding_reference_query_input_v11(copied)
        with pytest.raises(ERRORS):
            validate_reference_query_result_v11(
                copied, parse_embedding_reference_query_result(result_body(request))
            )
    result = parse_embedding_reference_query_result(result_body(request))
    with pytest.raises(ERRORS):
        validate_reference_query_result_v11(
            request, result.model_copy(update={"authority": "ADMIN"})
        )
    assert request == parse_embedding_reference_query_input_v11(input_body())


def test_input_text_bound_and_vector_extra_do_not_become_unbounded_payloads() -> None:
    document = input_body()
    document["rows"][0]["text"] = "가" * (262144 + 1)
    with pytest.raises(ERRORS):
        parse_embedding_reference_query_input_v11(seal(document, "request_sha256"))
    document = input_body()
    document["rows"][0]["vector"] = [0.1]
    with pytest.raises(ValueError, match="floats"):
        parse_embedding_reference_query_input_v11(document)
