"""Closed synthetic role-read values, not current source or runtime admission."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.similarity_materials import build_similarity_materials
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_contracts.workflow_similarity_read import (
    WorkflowSimilarityReadReply,
    WorkflowSimilarityReadRequest,
    WorkflowSimilarityRoleSelection,
    validate_workflow_similarity_read_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_similarity_materials_contracts import materials_case


def pair():
    context, anchor, entries = materials_case(count=2)
    selection = WorkflowSimilarityRoleSelection(
        workflow_id="workflow_" + "a" * 32,
        step_run_id="steprun_" + "b" * 32,
        plan_id="execplan_" + "c" * 32,
        plan_sha256="sha256:" + "d" * 64,
        query=CompletedSimilarityQuerySelection(
            workflow_id="workflow_" + "e" * 32,
            workflow_request_sha256="sha256:" + "f" * 64,
            context_request_sha256=context.request.request_sha256,
        ),
    )
    request = WorkflowSimilarityReadRequest(
        schema_version="system-rag-workflow-similarity-read-request/1.0",
        operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
        selection=selection,
    )
    reply = WorkflowSimilarityReadReply(
        schema_version="system-rag-workflow-similarity-read-reply/1.0",
        operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
        status="SUCCESS",
        request_sha256=content_sha256(request.model_dump(mode="json")),
        operator_id="operator_" + "a" * 32,
        context=context,
        materials=build_similarity_materials(context, anchor_profile=anchor, entries=entries),
        error_code=None,
    )
    return request, reply


def test_schema_precedes_models_and_packaged_resource_is_exact():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["system-rag-workflow-similarity-read"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-workflow-similarity-read"))


def test_exact_closed_round_trip_has_no_actor_in_request():
    request, reply = pair()
    assert WorkflowSimilarityReadRequest.model_validate(request) == request
    assert WorkflowSimilarityReadReply.model_validate_json(canonical_json_bytes(reply)) == reply
    validate_workflow_similarity_read_reply(request, reply, expected_operator_id=reply.operator_id)
    assert set(request.model_dump()) == {"schema_version", "operation", "selection"}


@pytest.mark.parametrize(
    "field", ("actor_id", "operator_id", "permissions", "path", "context", "vectors", "token")
)
def test_caller_cannot_supply_authority_or_materialization(field):
    request, _ = pair()
    with pytest.raises((ValueError, SchemaError)):
        WorkflowSimilarityReadRequest.model_validate(
            request.model_dump(mode="json") | {field: "not-authority"}
        )


@pytest.mark.parametrize("field", ("schema_version", "operation", "selection"))
def test_raw_missing_request_members_never_use_defaults(field):
    request, _ = pair()
    raw = request.model_dump(mode="json")
    del raw[field]
    with pytest.raises((ValueError, SchemaError)):
        WorkflowSimilarityReadRequest.model_validate(raw)


@pytest.mark.parametrize("field", ("workflow_id", "step_run_id", "plan_id", "plan_sha256", "query"))
def test_selection_is_exact_and_closed(field):
    request, _ = pair()
    raw = request.selection.model_dump(mode="json")
    del raw[field]
    with pytest.raises((ValueError, SchemaError)):
        WorkflowSimilarityRoleSelection.model_validate(raw)


@pytest.mark.parametrize(
    "fault", ("operator", "request", "context", "materials", "partial_failure")
)
def test_foreign_or_partial_reply_cannot_satisfy_a_role_read(fault):
    request, reply = pair()
    raw = deepcopy(reply.model_dump(mode="json"))
    if fault == "operator":
        raw["operator_id"] = "operator_" + "b" * 32
    elif fault == "request":
        raw["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "context":
        request = request.model_copy(
            update={
                "selection": request.selection.model_copy(
                    update={
                        "query": request.selection.query.model_copy(
                            update={"context_request_sha256": "sha256:" + "0" * 64}
                        )
                    }
                )
            }
        )
        raw["request_sha256"] = content_sha256(request.model_dump(mode="json"))
    elif fault == "materials":
        raw["materials"]["context_sha256"] = "sha256:" + "0" * 64
    else:
        raw.update(status="FAILED", error_code="SOURCE_REVOKED")
    with pytest.raises((ValueError, SchemaError)):
        validate_workflow_similarity_read_reply(
            request,
            WorkflowSimilarityReadReply.model_validate(raw),
            expected_operator_id=reply.operator_id,
        )
