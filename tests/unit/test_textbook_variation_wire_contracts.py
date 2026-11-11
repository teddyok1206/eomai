"""Successor wire contracts preserve exact-source history and require textbook scope."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api.errors import ApiError
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api.services.current_item_authoring_admission import (
    require_current_item_authoring_grounding,
)
from eom_api_contracts.workflows import (
    EducationalRetrievalIntentRequestV3,
    WorkflowStartRequest,
)
from eom_catalog_contracts import (
    CatalogApplicationRequest,
    CreateItemProductionEvidenceCommand,
    EducationalRetrievalRequirementV2,
    EducationalRetrievalRequirementV3,
    catalog_application_schema_route,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_web_gui.contracts import RequestDraftInput, RequestDraftUpdate
from eom_web_gui.request_drafts import normalize_request, update_draft, workflow_start_payload
from eom_workflow import WorkflowRequest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 11, tzinfo=UTC)


def _start() -> dict:
    draft = normalize_request(
        RequestDraftInput(original_request_text="교과서 범위 안에서 고정 기출을 변형해 주세요."),
        now=NOW,
        token="a" * 32,
    )
    update = {key: getattr(draft, key) for key in RequestDraftUpdate.model_fields}
    update.update(
        knowledge_grounding=True,
        curriculum_selected_unit_key="eom.is.middle.1-1",
        past_exam_variation={
            "source_item_revision_id": "itemrev_" + "a" * 32,
            "variation_axes": ["CONTEXT", "VALUES"],
        },
    )
    return workflow_start_payload(
        update_draft(draft, RequestDraftUpdate.model_validate(update), now=NOW),
        graph_corpus_key="integrated-science-textbooks",
    )


def _requirement() -> dict:
    return _start()["educational_retrieval"] | {
        "curriculum_root_key": "curriculum:eom.is.middle.1-1"
    }


def _validator(version: int) -> Draft202012Validator:
    paths = [f"schemas/api/v1/workflow-start-v{i}.schema.json" for i in range(1, 8)] + [
        "schemas/workflow/knowledge-item-brief-v1.schema.json",
        "schemas/workflow/content-team-material-requirement-v1.schema.json",
        "schemas/workflow/content-team-material-requirement-v2.schema.json",
        "schemas/knowledge/educational-retrieval-requirement-v1.schema.json",
        "schemas/knowledge/educational-retrieval-requirement-v2.schema.json",
        "schemas/knowledge/educational-retrieval-requirement-v3.schema.json",
        "schemas/knowledge/past-exam-variation-request-v1.schema.json",
        "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json",
    ]
    schemas = [json.loads((ROOT / path).read_text()) for path in paths]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    return Draft202012Validator(schemas[version - 1], registry=registry)


def test_new_resources_are_mirrored_and_registered() -> None:
    for canonical, packaged in (
        (
            "schemas/knowledge/educational-retrieval-requirement-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
            "educational-retrieval-requirement-v3.schema.json",
        ),
        (
            "schemas/catalog-application/catalog-application-request-v20.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application/"
            "catalog-application-request-v20.schema.json",
        ),
        (
            "schemas/api/v1/workflow-start-v7.schema.json",
            "packages/api_contracts/eom_api_contracts/schemas/workflow-start-v7.schema.json",
        ),
    ):
        assert (ROOT / canonical).read_bytes() == (ROOT / packaged).read_bytes()
    validate_contract("educational-retrieval-requirement-v3", _requirement())


def test_final_v3_requirement_requires_textbook_and_api_resolved_scope() -> None:
    value = _requirement()
    result = EducationalRetrievalRequirementV3.model_validate(value)
    assert isinstance(result, EducationalRetrievalRequirementV2)
    assert result.source_classes == ("PAST_EXAM", "TEXTBOOK")
    with pytest.raises(ValidationError):
        EducationalRetrievalRequirementV2.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("educational-retrieval-requirement-v2", value)


@pytest.mark.parametrize(
    "change",
    [
        {"curriculum_root_key": None},
        {"source_classes": ["PAST_EXAM"]},
        {"source_classes": ["TEXTBOOK", "PAST_EXAM"]},
        {"topic_keys": ["topic:unbounded"]},
        {"requester_role": "ADMIN"},
    ],
)
def test_final_requirement_rejects_unbounded_or_source_only_payloads(change: dict) -> None:
    value = _requirement() | change
    with pytest.raises(ValidationError):
        EducationalRetrievalRequirementV3.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("educational-retrieval-requirement-v3", value)


def test_v7_accepts_new_intent_and_keeps_historical_v6_readable() -> None:
    value = _start()
    assert value["educational_retrieval"]["curriculum_root_key"] is None
    assert isinstance(
        WorkflowStartRequest.model_validate(value).educational_retrieval,
        EducationalRetrievalIntentRequestV3,
    )
    _validator(7).validate(value)
    with pytest.raises(SchemaError):
        _validator(6).validate(value)
    old = deepcopy(value)
    old["educational_retrieval"].update(
        schema_version="educational-retrieval-requirement/2.0", source_classes=["PAST_EXAM"]
    )
    _validator(6).validate(old)
    _validator(7).validate(old)
    assert WorkflowStartRequest.model_validate(old).educational_retrieval is not None


@pytest.mark.parametrize(
    "unit,root",
    (
        (
            "eom.is.middle.1-1",
            "curriculum.eom.editorial.integrated-science.volume-i.large-1.middle-1",
        ),
        (
            "eom.is.middle.3-3",
            "curriculum.eom.editorial.integrated-science.volume-i.large-3.middle-3",
        ),
    ),
)
def test_public_v3_conversion_binds_selected_unit_and_preserves_exact_source(
    unit: str, root: str
) -> None:
    payload = _start()
    payload["item_brief"]["curriculum_selected_unit_key"] = unit
    original_payload = deepcopy(payload)
    public = WorkflowStartRequest.model_validate(payload)
    original_public = public.model_dump(mode="json")

    internal = _workflow_request_from_api(public)
    requirement = internal.educational_retrieval
    assert type(requirement) is EducationalRetrievalRequirementV3
    assert requirement.curriculum_root_key == root
    assert requirement.topic_keys == ()
    assert requirement.source_classes == ("PAST_EXAM", "TEXTBOOK")
    assert (
        requirement.past_exam_variation.model_dump(mode="json")
        == (payload["educational_retrieval"]["past_exam_variation"])
    )
    assert internal.item_brief is not None
    assert internal.item_brief.curriculum_scope.selected_unit_key == unit
    assert internal.item_brief.curriculum_scope.graph_root_stable_key == root
    assert WorkflowRequest.model_validate(internal.model_dump(mode="json")) == internal
    require_current_item_authoring_grounding(internal)
    validate_contract("educational-retrieval-requirement-v3", requirement.model_dump(mode="json"))
    assert public.model_dump(mode="json") == original_public
    assert payload == original_payload


def test_public_v3_conversion_rejects_unknown_unit_and_internal_mismatched_root() -> None:
    payload = _start()
    payload["item_brief"]["curriculum_selected_unit_key"] = "eom.is.middle.1-7"
    with pytest.raises(ApiError) as captured:
        _workflow_request_from_api(WorkflowStartRequest.model_validate(payload))
    assert captured.value.error_code == "WORKFLOW_CURRICULUM_SELECTION_INVALID"

    internal = _workflow_request_from_api(WorkflowStartRequest.model_validate(_start()))
    mismatched = internal.model_dump(mode="json")
    mismatched["educational_retrieval"]["curriculum_root_key"] = (
        "curriculum.eom.editorial.integrated-science.volume-i.large-3.middle-3"
    )
    with pytest.raises(ValidationError):
        WorkflowRequest.model_validate(mismatched)


@pytest.mark.parametrize("change", ("root", "unit", "version", "textbook"))
def test_public_v3_intent_cannot_choose_server_scope_or_omit_textbook(change: str) -> None:
    value = _start()
    if change == "root":
        value["educational_retrieval"]["curriculum_root_key"] = "curriculum:forged"
    elif change == "unit":
        value["item_brief"]["curriculum_selected_unit_key"] = None
    elif change == "version":
        value["definition_version"] = "1.15.0"
    else:
        value["educational_retrieval"]["source_classes"] = ["PAST_EXAM"]
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate(value)
    with pytest.raises(SchemaError):
        _validator(7).validate(value)


def test_catalog_v3_command_selects_v20_and_preserves_v2_wire() -> None:
    body = {
        "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
        "requirement": _requirement(),
        "evidence_budget": {
            "max_documents": 8,
            "max_item_revisions": 4,
            "max_graph_nodes": 64,
            "max_claims": 32,
            "max_context_tokens": 8000,
        },
        "access_policy_revision_id": "accessrev_" + "b" * 32,
        "access_policy_sha256": "sha256:" + "c" * 64,
        "requester_role": "EDITOR",
        "requester_permission_keys": ["item:read"],
        "requested_by": "editor-test",
        "solution_evidence_requirement": "REQUIRE_ACCEPTED_SOLUTION_REPORT",
    }
    payload = body | {
        "idempotency_key": "variation-with-textbook-test",
        "submission_sha256": content_sha256(body),
    }
    command = CreateItemProductionEvidenceCommand.model_validate(payload)
    assert isinstance(command.requirement, EducationalRetrievalRequirementV3)
    assert CatalogApplicationRequest.model_validate(payload).root == command
    route = catalog_application_schema_route(
        command.operation,
        retrieval_requirement_schema_version=command.requirement.schema_version,
    )
    assert route.request_schema == "catalog-application-request-v20"
    assert route.response_schema == "catalog-application-response-v15"
    validate_contract(route.request_schema, payload)
    historical = catalog_application_schema_route(command.operation)
    assert historical.request_schema == "catalog-application-request-v17"
    with pytest.raises(SchemaError):
        validate_contract(historical.request_schema, payload)
    body["requirement"] = body["requirement"] | {
        "schema_version": "educational-retrieval-requirement/2.0",
        "source_classes": ["PAST_EXAM"],
        "curriculum_root_key": None,
    }
    old = body | {
        "idempotency_key": "historical-variation-test",
        "submission_sha256": content_sha256(body),
    }
    validate_contract(historical.request_schema, old)
    validate_contract(route.request_schema, old)
