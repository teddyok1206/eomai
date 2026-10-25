"""Finite pointer-only messages; no source/Identity/model admission is implied."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV3,
    ReferenceQueryPrepareRequestV3,
    parse_single_reference_query_prepare_request,
    parse_supported_reference_query_prepare_reply,
    parse_supported_reference_query_prepare_request,
    routed_reference_query_error_reply,
    validate_supported_reference_query_prepare_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_prepare_contracts import request_body


def bulk_body(count=2):
    requests = []
    for i in range(count):
        one = request_body()
        one["source_item_revision_id"] = "itemrev_" + f"{i:032x}"
        requests.append(seal(one, "request_sha256"))
    return seal(
        dict(
            schema_version="system-rag-reference-query-prepare-request/3.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id="queryprepare_" + "e" * 32,
            idempotency_key="original-bounded-query-batch",
            requests=requests,
        ),
        "request_sha256",
    )


def observation_body(request, *, ready=False):
    singles = (
        request.requests if isinstance(request, ReferenceQueryPrepareRequestV3) else (request,)
    )
    children = []
    for i, single in enumerate(singles):
        workflow = "workflow_" + f"{i:032x}"
        children.append(
            dict(
                ordinal=i,
                source_item_revision_id=single.source_item_revision_id,
                workflow_id=workflow if ready else None,
                state="COMPLETED" if ready else "PENDING",
                selection=dict(
                    workflow_id=workflow,
                    workflow_request_sha256="sha256:" + "c" * 64,
                    context_request_sha256="sha256:" + "d" * 64,
                )
                if ready
                else None,
            )
        )
    return dict(
        schema_version="system-rag-reference-query-prepare-reply/3.0",
        operation="PREPARE_REFERENCE_QUERY",
        operation_id=request.operation_id,
        request_sha256=request.request_sha256,
        request_schema_version=request.schema_version,
        status="READY" if ready else "PENDING",
        preparation=dict(
            artifact_id="artifact_" + "a" * 32,
            artifact_revision_id="rev_" + "b" * 32,
            member_path="preparation.json",
            sha256="sha256:" + "1" * 64,
            schema_ref="eom://schemas/workflow/reference-query-routed-preparation/1.0",
            media_type="application/json",
        ),
        parent_request_sha256="sha256:" + "2" * 64,
        device="CUDA" if ready else None,
        children=children,
        workflow_id=children[0]["workflow_id"] if len(children) == 1 else None,
        selection=children[0]["selection"] if ready and len(children) == 1 else None,
        error_code=None,
    )


def test_schema_is_closed_mirrored_and_registered_without_changing_predecessors():
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-reference-query-prepare-v3"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema("system-rag-reference-query-prepare-v3")
    Draft202012Validator.check_schema(schema)
    for name in ("request", "reply", "child", "preparation"):
        shape = schema["$defs"][name]
        assert shape["additionalProperties"] is False
        assert set(shape["properties"]) == set(shape["required"])


@pytest.mark.parametrize("count", (1, 2, 16))
@pytest.mark.parametrize("ready", (False, True))
def test_original_bounded_order_pending_without_workflow_and_completed_pointer(count, ready):
    request = parse_supported_reference_query_prepare_request(bulk_body(count))
    reply = parse_supported_reference_query_prepare_reply(observation_body(request, ready=ready))
    validate_supported_reference_query_prepare_reply(request, reply)
    assert len(reply.children) == count
    assert (reply.selection is not None) == (ready and count == 1)
    assert reply.device == ("CUDA" if ready else None)
    with pytest.raises(ValueError):
        parse_single_reference_query_prepare_request(request)


@pytest.mark.parametrize("family", ("1.0", "1.1", "2.0"))
def test_successor_reply_explicitly_binds_a_preserved_single_request_family(family):
    body = request_body(
        consumer_purpose="ITEM_AUTHORING" if family != "1.0" else "PAST_EXAM_VARIATION"
    )
    body["schema_version"] = "system-rag-reference-query-prepare-request/" + family
    request = parse_single_reference_query_prepare_request(seal(body, "request_sha256"))
    reply = ReferenceQueryPrepareReplyV3.model_validate(observation_body(request))
    validate_supported_reference_query_prepare_reply(request, reply)
    assert reply.workflow_id is None and reply.selection is None


@pytest.mark.parametrize(
    "fault",
    (
        "empty",
        "too_many",
        "duplicate",
        "recursive",
        "graph",
        "purpose",
        "mixed",
        "hash",
        "extra",
        "hidden",
    ),
)
def test_finite_request_rejects_mixed_authority_population_or_recursive_envelope(fault):
    body = bulk_body()
    if fault == "empty":
        body["requests"] = []
    elif fault == "too_many":
        body = bulk_body(17)
    elif fault == "duplicate":
        body["requests"][1] = deepcopy(body["requests"][0])
    elif fault == "recursive":
        body["requests"][0] = bulk_body(1)
    elif fault == "graph":
        body["requests"][1]["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
        body["requests"][1] = seal(body["requests"][1], "request_sha256")
    elif fault == "purpose":
        body["requests"][1].update(
            schema_version="system-rag-reference-query-prepare-request/1.1",
            consumer_purpose="ITEM_REVIEW",
        )
        body["requests"][1] = seal(body["requests"][1], "request_sha256")
    elif fault == "mixed":
        body["requests"][1].update(
            schema_version="system-rag-reference-query-prepare-request/2.0",
            consumer_purpose="PAST_EXAM_VARIATION",
        )
        body["requests"][1] = seal(body["requests"][1], "request_sha256")
    elif fault == "extra":
        body["actor_id"] = "operator_" + "a" * 32
    elif fault == "hidden":
        body = ReferenceQueryPrepareRequestV3.model_validate(body).model_copy(
            update={"roles": ["ADMIN"]}
        )
    if isinstance(body, dict):
        body = seal(body, "request_sha256")
        if fault == "hash":
            body["request_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequestV3.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    (
        "order",
        "duplicate_source",
        "fake_summary",
        "wrong_child",
        "not_complete",
        "missing_preparation",
        "missing_device",
        "wrong_family",
        "wrong_hash",
        "wrong_source",
        "extra",
        "bool_ordinal",
    ),
)
def test_observation_cannot_launder_missing_wrong_or_uncompleted_evidence(fault):
    request = ReferenceQueryPrepareRequestV3.model_validate(bulk_body())
    body = observation_body(request, ready=True)
    if fault == "order":
        body["children"].reverse()
    elif fault == "duplicate_source":
        body["children"][1]["source_item_revision_id"] = body["children"][0][
            "source_item_revision_id"
        ]
    elif fault == "fake_summary":
        body["workflow_id"] = body["children"][0]["workflow_id"]
    elif fault == "wrong_child":
        body["children"][0]["selection"]["workflow_id"] = "workflow_" + "e" * 32
    elif fault == "not_complete":
        body["children"][0].update(state="PENDING", selection=None)
    elif fault == "missing_preparation":
        body["preparation"] = None
    elif fault == "missing_device":
        body["device"] = None
    elif fault == "wrong_family":
        body["request_schema_version"] = "system-rag-reference-query-prepare-request/2.0"
    elif fault == "wrong_hash":
        body["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "wrong_source":
        body["children"][0]["source_item_revision_id"] = "itemrev_" + "f" * 32
    elif fault == "extra":
        body["auth"] = {}
    else:
        body["children"][0]["ordinal"] = False
    with pytest.raises((ValueError, SchemaError)):
        validate_supported_reference_query_prepare_reply(
            request, ReferenceQueryPrepareReplyV3.model_validate(body)
        )


def test_authority_denial_is_failure_not_optional_absence_or_cpu_fallback():
    request = ReferenceQueryPrepareRequestV3.model_validate(bulk_body())
    denied = routed_reference_query_error_reply(request, error_code="SOURCE_ACCESS_DENIED")
    validate_supported_reference_query_prepare_reply(request, denied)
    assert denied.status == "FAILED" and denied.preparation is None
    with pytest.raises((ValueError, SchemaError)):
        routed_reference_query_error_reply(
            request, status="UNAVAILABLE", error_code="SOURCE_ACCESS_DENIED"
        )
