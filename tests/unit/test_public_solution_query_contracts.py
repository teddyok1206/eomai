"""Public QUERY2 metadata; synthetic numerical rows, never source/runtime authority."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    parse_embedding_reference_query_input,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryExecutionPointer,
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import embedding_space, seal, vector_shard
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_embedding_reference_query_contracts import query_input_body
from tests.unit.test_public_solution_encoding import public_entry, public_recipe


def public_query_input(*, device="CPU", creative=False):
    query = embedding_space(device=device, purpose="QUERY")
    prepared = prepare_public_solution_encoding(
        public_entry(creative=creative), space=query, storage_partition="public-solution"
    ).input
    body = query_input_body() | {
        "schema_version": "embedding-reference-query-input/2.0",
        "spaces": {
            "query": query.model_dump(mode="json"),
            "document": embedding_space(device=device).model_dump(mode="json"),
        },
        "recipe": public_recipe().model_dump(mode="json"),
        "rows": [prepared.model_dump(mode="json") | {"view": "CONCRETE_FACETS"}],
        "batch_size": 4,
        "threads": 4,
        "input_set_sha256": embedding_input_set_sha256((prepared.encoding,)),
    }
    return PublicSolutionQueryInput.model_validate(seal(body, "request_sha256"))


def public_query_result(request):
    shard = vector_shard(tuple(row.encoding for row in request.rows), space=request.spaces.query)
    return PublicSolutionQueryResult.model_validate(
        seal(
            {
                "schema_version": "embedding-reference-query-result/2.0",
                **{
                    key: getattr(request, key)
                    for key in (
                        "job_id",
                        "query_request_id",
                        "context_request_sha256",
                        "request_sha256",
                        "spaces",
                        "recipe",
                        "input_set_sha256",
                    )
                },
                "shard": shard.model_dump(mode="json"),
                "view_rows": [
                    {
                        "view": "CONCRETE_FACETS",
                        "row_index": 0,
                        "encoding_sha256": request.rows[0].encoding.encoding_sha256,
                    }
                ],
            },
            "result_sha256",
        )
    )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_public_query_uses_the_same_text_for_both_report_families_and_real_query_purpose(device):
    past = public_query_input(device=device)
    creative = public_query_input(device=device, creative=True)
    assert creative == past
    assert past.rows[0].text == public_entry().public_solution.text
    assert past.spaces.query.purpose == "QUERY" and past.spaces.document.purpose == "DOCUMENT"
    result = public_query_result(past)
    validate_public_solution_query_result(past, result)
    assert result.shard.row_count == 1 and result.shard.space == past.spaces.query
    assert result.shard.schema_version == "embedding-vector-shard/1.0"
    assert past.batch_size == 4 and len(past.rows) == 1  # no padding
    assert canonical_json_bytes(
        PublicSolutionQueryResult.model_validate(result)
    ) == canonical_json_bytes(result)
    pointer = PublicSolutionQueryExecutionPointer(
        job_id=past.job_id,
        query_request_id=past.query_request_id,
        request_sha256=past.request_sha256,
        input_set_sha256=past.input_set_sha256,
        result_member=member(
            "result.json", PUBLIC_SOLUTION_QUERY_RESULT_REF, result.model_dump(mode="json")
        ),
        result_sha256=result.result_sha256,
    )
    assert pointer.result_member.sha256 == content_sha256(result.model_dump(mode="json"))


def test_old_query_parsers_and_old_result_members_do_not_reinterpret_recipe2():
    request = public_query_input()
    result = public_query_result(request)
    for parse in (parse_embedding_reference_query_input, parse_embedding_reference_query_input_v11):
        with pytest.raises((ValueError, SchemaError)):
            parse(request)
    with pytest.raises((ValueError, SchemaError)):
        parse_embedding_reference_query_result(result)
    with pytest.raises(ValueError):
        PublicSolutionQueryExecutionPointer(
            job_id=request.job_id,
            query_request_id=request.query_request_id,
            request_sha256=request.request_sha256,
            input_set_sha256=request.input_set_sha256,
            result_member=member(
                "result.json",
                "eom://schemas/knowledge/embedding-reference-query-result/1.0",
                result.model_dump(mode="json"),
            ),
            result_sha256=result.result_sha256,
        )


@pytest.mark.parametrize(
    "change", ["view", "extra", "text", "space", "recipe", "input_set", "extra_row", "overflow"]
)
def test_public_query_rejects_drift_without_rewriting_or_truncating(change):
    request = public_query_input()
    body = deepcopy(request.model_dump(mode="json"))
    if change == "view":
        body["rows"][0]["view"] = "CONTENT_ONLY"
    elif change == "extra":
        body["authority"] = "ADMIN"
    elif change == "text":
        body["rows"][0]["text"] = "바꾼 내용"
    elif change == "space":
        body["spaces"]["query"] = body["spaces"]["document"]
    elif change == "recipe":
        body["recipe"]["facets"] = "EXACT_PROFILE_CLAIMS"
    elif change == "input_set":
        body["input_set_sha256"] = "sha256:" + "f" * 64
    elif change == "extra_row":
        body["rows"] *= 2
    else:
        text = "가" * 87382
        row = body["rows"][0]
        row["text"] = text
        row["encoding"] = seal(
            row["encoding"] | {"input_text_sha256": content_sha256(text)}, "encoding_sha256"
        )
        body["input_set_sha256"] = content_sha256([row["encoding"]])
    with pytest.raises((ValueError, SchemaError)):
        PublicSolutionQueryInput.model_validate(seal(body, "request_sha256"))


@pytest.mark.parametrize("change", ["request", "job", "view", "ordinal", "purpose"])
def test_public_query_result_requires_its_exact_input_and_view_row(change):
    request = public_query_input()
    body = public_query_result(request).model_dump(mode="json")
    if change == "request":
        body["request_sha256"] = "sha256:" + "f" * 64
    elif change == "job":
        body["job_id"] = "job_" + "f" * 32
    elif change == "view":
        body["view_rows"][0]["view"] = "CONTENT_ONLY"
    elif change == "ordinal":
        body["view_rows"][0]["row_index"] = 1
    else:
        body["shard"]["space"] = body["spaces"]["document"]
    with pytest.raises((ValueError, SchemaError)):
        result = PublicSolutionQueryResult.model_validate(seal(body, "result_sha256"))
        validate_public_solution_query_result(request, result)


def test_query_schema_is_pinned_and_packaged_identically():
    root = Path(__file__).resolve().parents[2]
    record = CATALOG_SCHEMA_RESOURCES["public-solution-query-v2"]
    raw = (root / record.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / record.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == record.sha256
