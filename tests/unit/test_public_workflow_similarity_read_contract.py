"""Closed public read frames; synthetic pins, no current source/QUERY authority."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.public_workflow_similarity_read import (
    PublicWorkflowSimilarityReadReply,
    PublicWorkflowSimilarityReadRequest,
    validate_public_workflow_similarity_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_contracts.workflow_similarity_read import WorkflowSimilarityReadReply
from eom_catalog_service.workflow_similarity_read_dispatch import (
    dispatch_workflow_similarity_read_frame,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_public_similarity_materials_contracts import material_case


def public_pair(registered=False):
    context, materials = material_case(registered)
    request = PublicWorkflowSimilarityReadRequest(
        schema_version="system-rag-workflow-similarity-read-request/2.0",
        operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
        selection={
            "workflow_id": "workflow_" + "1" * 32,
            "step_run_id": "steprun_" + "2" * 32,
            "plan_id": "execplan_" + "3" * 32,
            "plan_sha256": "sha256:" + "4" * 64,
            "query": {
                "workflow_id": "workflow_" + "5" * 32,
                "workflow_request_sha256": "sha256:" + "6" * 64,
                "context_request_sha256": context.request.request_sha256,
            },
        },
    )
    reply = PublicWorkflowSimilarityReadReply(
        schema_version="system-rag-workflow-similarity-read-reply/2.0",
        operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
        status="SUCCESS",
        request_sha256=content_sha256(request.model_dump(mode="json")),
        operator_id="operator_" + "7" * 32,
        context=context,
        materials=materials,
        error_code=None,
    )
    return request, reply


def test_public_read_schema_resource_matches_canonical_and_keeps_v1_immutable():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-workflow-similarity-read-v2"]
    payload = (root / resource.canonical_path).read_bytes()
    assert (
        payload
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(payload) == resource.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-workflow-similarity-read-v2"))
    assert (
        sha256_bytes(
            (
                root / "schemas/knowledge/system-rag-workflow-similarity-read-v1.schema.json"
            ).read_bytes()
        )
        == "sha256:4173690a974ae475f4dcaca9404003a16d644b37b8d970eb798515c72ad6a384"
    )


@pytest.mark.parametrize("registered", (False, True))
def test_public_read_closed_roundtrip_keeps_materials_and_context_family(registered):
    request, reply = public_pair(registered)
    assert (
        PublicWorkflowSimilarityReadReply.model_validate_json(canonical_json_bytes(reply)) == reply
    )
    validate_public_workflow_similarity_reply(
        request, reply, expected_operator_id=reply.operator_id
    )
    with pytest.raises((ValueError, SchemaError)):
        WorkflowSimilarityReadReply.model_validate(reply.model_dump(mode="json"))


@pytest.mark.parametrize("field", ("operator_id", "path", "latest", "native_launch"))
def test_public_read_request_accepts_no_model_authority_or_execution(field):
    request, _ = public_pair()
    raw = request.model_dump(mode="json") | {field: "untrusted"}
    with pytest.raises((ValueError, SchemaError)):
        PublicWorkflowSimilarityReadRequest.model_validate(raw)


@pytest.mark.parametrize("field", ("operator_id", "request_sha256", "context_request"))
def test_substitution_is_denied(field):
    request, reply = public_pair()
    if field == "context_request":
        body = request.model_dump(mode="json")
        body["selection"]["query"]["context_request_sha256"] = "sha256:" + "0" * 64
        request = PublicWorkflowSimilarityReadRequest.model_validate(body)
    else:
        raw = reply.model_dump(mode="json")
        raw[field] = "operator_" + "0" * 32 if field == "operator_id" else "sha256:" + "0" * 64
        reply = PublicWorkflowSimilarityReadReply.model_validate(raw)
    with pytest.raises(ValueError):
        validate_public_workflow_similarity_reply(
            request, reply, expected_operator_id="operator_" + "7" * 32
        )


def test_public_failed_response_is_closed_and_does_not_expose_context():
    request, _ = public_pair()
    raw = dispatch_workflow_similarity_read_frame(None, canonical_json_bytes(request) + b"\n")
    reply = PublicWorkflowSimilarityReadReply.model_validate_json(raw)
    assert reply.status == "FAILED" and reply.error_code == "WORKFLOW_SIMILARITY_UNAVAILABLE"
    assert reply.context is None and reply.materials is None and reply.operator_id is None
    assert reply.request_sha256 == content_sha256(request)


@pytest.mark.parametrize("fault", ("material_hash", "missing_materials", "failed_context"))
def test_public_success_cannot_omit_or_rebind_materials(fault):
    _, reply = public_pair()
    raw = deepcopy(reply.model_dump(mode="json"))
    if fault == "material_hash":
        raw["materials"]["materials_sha256"] = "sha256:" + "0" * 64
    elif fault == "missing_materials":
        raw["materials"] = None
    else:
        raw["context"]["status"] = "FAILED"
    with pytest.raises((ValueError, SchemaError)):
        PublicWorkflowSimilarityReadReply.model_validate(raw)
