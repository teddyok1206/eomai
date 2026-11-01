"""Private context2 metadata and unchanged QUERY2 closure; no live permission grant."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.private_chat_similarity import (
    PRIVATE_CHAT_LIMITATION_ORDER,
    PrivateChatSimilarityContext,
    PrivateChatSimilarityRequest,
)
from eom_catalog_contracts.private_chat_similarity_v2 import (
    PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA,
    PrivateChatPublicPopulation,
    PrivateChatSimilarityContextV2,
    PrivateChatSimilarityRequestV2,
    parse_supported_private_chat_similarity_context,
    parse_supported_private_chat_similarity_request,
    validate_private_chat_public_query_execution,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_similarity_service import compose, private_public_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_similarity_service import case as legacy_case
from tests.unit.test_private_chat_similarity_service import compose as legacy_compose


def context():
    return compose(*private_public_case())


def terminal(status, *, reason=None, index=True):
    request = private_public_case()[0].model_dump(mode="json")
    if not index:
        request["views"][0]["index"] = None
        request = seal(request, "request_sha256")
    body = dict(
        schema_version="system-rag-private-chat-similarity-context/2.0",
        request=request,
        status=status,
        population=None,
        query_execution=None,
        candidates=[],
        limitations=list(PRIVATE_CHAT_LIMITATION_ORDER[:3]),
        unavailable_reason=reason,
        error_code="SOURCE_POINTER_INVALID" if status == "FAILED" else None,
    )
    if status == "UNAVAILABLE":
        body["limitations"].append("VECTOR_NOT_AVAILABLE")
    return seal(body, "context_sha256")


def test_context2_schema_is_valid_mirrored_and_independently_pinned():
    resource = CATALOG_SCHEMA_RESOURCES[PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA]
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
        == "sha256:1cd60d0df32bd5b08d72211d5aab4fd5be53e5fe4a2550c3ed0f79002671326b"
    )
    Draft202012Validator.check_schema(load_schema(PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA))


def test_public_context2_and_legacy1_parse_only_their_explicit_versions():
    request = private_public_case()[0]
    value = context()
    assert parse_supported_private_chat_similarity_request(request) == request
    assert parse_supported_private_chat_similarity_context(value) == value
    old_request, old_owner = legacy_case()
    old_context = legacy_compose(old_request, old_owner)
    assert parse_supported_private_chat_similarity_request(old_request) == old_request
    assert parse_supported_private_chat_similarity_context(old_context) == old_context
    for model, invalid in (
        (PrivateChatSimilarityRequest, request),
        (PrivateChatSimilarityContext, value),
        (PrivateChatSimilarityRequestV2, old_request),
        (PrivateChatSimilarityContextV2, old_context),
    ):
        with pytest.raises((ValueError, SchemaError)):
            model.model_validate(invalid.model_dump(mode="json"))
    for document in (request, value):
        validate_contract(PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA, document.model_dump(mode="json"))
        assert type(document).model_validate_json(canonical_json_bytes(document)) == document


@pytest.mark.parametrize(
    "field,value",
    (
        ("anchor", {}),
        ("authority", "ADMIN"),
        ("text", "private"),
        ("vector_mode", "OPTIONAL"),
        ("consumer_purpose", "ITEM_DATABASE_SEARCH"),
        ("maximum_sources", True),
        ("maximum_sources", 16385),
        ("top_k", 65),
        ("schema_version", "system-rag-private-chat-similarity-request/3.0"),
    ),
)
def test_request_does_not_admit_fictional_sources_authority_or_implicit_coercion(field, value):
    body = private_public_case()[0].model_dump(mode="json") | {field: value}
    body = seal(body, "request_sha256")
    with pytest.raises((ValueError, SchemaError)):
        validate_contract(PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA, body)
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatSimilarityRequestV2.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    (
        "request_hash",
        "context_hash",
        "copied_request_extra",
        "copied_recipe_extra",
        "count_order",
        "self_subtraction",
        "rank",
        "duplicate",
        "query_basis",
        "query_member",
        "flags",
        "status",
        "top_k",
        "candidate_class",
    ),
)
def test_semantic_closure_rejects_inconsistent_counts_hashes_private_basis_and_candidates(fault):
    value = context()
    if fault == "copied_request_extra":
        document = value.model_copy(
            update={"request": value.request.model_copy(update={"authority": "ADMIN"})}
        )
    elif fault == "copied_recipe_extra":
        view = value.request.views[0]
        document = value.model_copy(
            update={
                "request": value.request.model_copy(
                    update={
                        "views": (
                            view.model_copy(
                                update={
                                    "recipe": view.recipe.model_copy(
                                        update={"extra": "not allowed"}
                                    )
                                }
                            ),
                        )
                    }
                )
            }
        )
    else:
        body = value.model_dump(mode="json")
        if fault == "request_hash":
            body["request"]["request_sha256"] = "sha256:" + "f" * 64
        elif fault == "context_hash":
            body["context_sha256"] = "sha256:" + "f" * 64
        elif fault == "count_order":
            body["population"]["authorized_source_count"] = 2
        elif fault == "self_subtraction":
            body["population"]["scored_count"] -= 1
        elif fault == "rank":
            body["candidates"][0]["observation"]["rank"] = 2
        elif fault == "duplicate":
            body["candidates"][1] = deepcopy(body["candidates"][0])
            body["candidates"][1]["observation"]["rank"] = 2
        elif fault == "query_basis":
            body["query_execution"]["basis_sha256"] = "sha256:" + "f" * 64
        elif fault == "query_member":
            body["query_execution"]["result_member"]["artifact_revision_id"] = "rev_" + "f" * 32
        elif fault == "flags":
            body["limitations"].append("PARTIAL_VIEW_COVERAGE")
        elif fault == "status":
            body["status"] = "PARTIAL"
        elif fault == "top_k":
            body["request"]["top_k"] = 1
            body["request"] = seal(body["request"], "request_sha256")
        else:
            body["request"]["source_classes"] = ["PAST_EXAM"]
            body["request"] = seal(body["request"], "request_sha256")
        document = body if fault == "context_hash" else seal(body, "context_sha256")
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatSimilarityContextV2.model_validate(document)


@pytest.mark.parametrize(
    "status,reason,index",
    (
        ("FAILED", None, False),
        ("FAILED", None, True),
        ("UNAVAILABLE", "INDEX_NOT_PREPARED", False),
        ("UNAVAILABLE", "QUERY_NOT_OFFERED", True),
        ("UNAVAILABLE", "INPUT_OVERFLOW", True),
    ),
)
def test_unavailable_and_failed_do_not_claim_no_matches_or_disclose_candidate_data(
    status, reason, index
):
    document = terminal(status, reason=reason, index=index)
    validate_contract(PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA, document)
    value = PrivateChatSimilarityContextV2.model_validate(document)
    assert value.population is None and value.query_execution is None and not value.candidates
    assert "NO_RELATED_CANDIDATES" not in value.limitations


@pytest.mark.parametrize(
    "status,reason,index",
    (
        ("UNAVAILABLE", "INDEX_NOT_PREPARED", True),
        ("UNAVAILABLE", "QUERY_NOT_OFFERED", False),
        ("UNAVAILABLE", "INPUT_OVERFLOW", False),
    ),
)
def test_json_schema_itself_enforces_missing_index_reason_consistency(status, reason, index):
    document = terminal(status, reason=reason, index=index)
    with pytest.raises((ValueError, SchemaError)):
        validate_contract(PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA, document)
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatSimilarityContextV2.model_validate(document)


def test_available_context_requires_an_actual_index_in_json_schema_not_only_pydantic():
    document = context().model_dump(mode="json")
    document["request"]["views"][0]["index"] = None
    document["request"] = seal(document["request"], "request_sha256")
    document = seal(document, "context_sha256")
    with pytest.raises((ValueError, SchemaError)):
        validate_contract(PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA, document)


def test_population_allows_full_16384_without_approved_item_self_subtraction():
    document = context().population.model_dump(mode="json")
    for key in (
        "authorized_source_count",
        "available_report_count",
        "available_binding_count",
        "scored_count",
    ):
        document[key] = 16384
    assert PrivateChatPublicPopulation.model_validate(document).scored_count == 16384
    for key in (
        "authorized_source_count",
        "available_report_count",
        "available_binding_count",
        "scored_count",
    ):
        with pytest.raises(ValueError):
            PrivateChatPublicPopulation.model_validate(document | {key: True})


@pytest.mark.parametrize("fault", ("request", "result", "result_member", "shard_member"))
def test_committed_query_closure_rejects_copied_extra_fields_before_any_repair(fault):
    value = context()
    _, _, _, query = private_public_case()
    values = {
        field: getattr(query, field)
        for field in ("request", "result", "result_member", "shard_member")
    }
    values[fault] = values[fault].model_copy(update={"authority": TEXT})
    with pytest.raises(
        ValueError, match=r"^PRIVATE_CHAT_PUBLIC_CONTEXT_NATIVE_ASSOCIATION_INVALID$"
    ):
        validate_private_chat_public_query_execution(value, **values)
