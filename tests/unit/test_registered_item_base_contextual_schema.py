"""Source-aware output subset; no models, database or historical result rewrites."""

import ast
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisBaseReferenceNode,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeNodeType,
    knowledge_node_id_prefix,
)
from eom_catalog_contracts.validation import load_schema as load_catalog_schema
from eom_identifiers import content_sha256
from eom_workflow import schemas as owner
from eom_workflow.models import ArtifactSpec, KnowledgeAnalysisWorkerRequest, RoleWorkerInput
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_knowledge_analysis_document_contracts import proposal_v3, request_v3
from tests.unit.test_registered_item_solution_application import source_fixture

SCHEMA = "knowledge-analysis-proposal-result@1.0"


def worker_input(request):
    return RoleWorkerInput(
        protocol_version="workflow-role/1.4.0",
        job_id="job_" + "a" * 32,
        workflow_id="workflow_" + "b" * 32,
        step_run_id="steprun_" + "c" * 32,
        attempt=1,
        role="support",
        request=KnowledgeAnalysisWorkerRequest(analysis_request=request),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "d" * 32, revision_id="rev_" + "e" * 32
        ),
    )


def sample():
    request, proposal, _source = source_fixture()
    parsed = worker_input(request)
    return parsed, result(parsed, proposal)


def result(parsed, proposal, *, protocol="workflow-role/1.4.0"):
    return dict(
        schema_version="1.0",
        protocol_version=protocol,
        job_id=parsed.job_id,
        workflow_id=parsed.workflow_id,
        step_run_id=parsed.step_run_id,
        role="support",
        status="ok",
        artifact=parsed.artifact.model_dump(mode="json"),
        output={
            "proposal": KnowledgeAnalysisWorkerProposal.model_validate(proposal).model_dump(
                mode="json"
            )
        },
        completed_at=parsed.request.analysis_request.created_at.isoformat().replace("+00:00", "Z"),
    )


def test_shared_reference_vocabulary_is_reused_in_disjoint_type_paired_closed_branches():
    parsed, _value = sample()
    before = owner.load_codex_result_schema(SCHEMA)
    snapshot = deepcopy(before)
    schema = owner.constrained_result_schema(SCHEMA, parsed)
    shared = load_catalog_schema("knowledge-analysis-solution-types-v1")["$defs"][
        "typedReferenceNode"
    ]["properties"]
    original = before["$defs"]["AnalysisV2_proposedNode"]
    branches = schema["$defs"]["KnowledgeAnalysisWorkerProposal"]["properties"]["nodes"]["items"][
        "anyOf"
    ]
    references, other = branches[:-1], branches[-1]
    reference_kinds = {branch["properties"]["node_type"]["enum"][0] for branch in references}
    assert len(reference_kinds) == len(references)
    other_kinds = set(other["properties"]["node_type"]["enum"])
    assert reference_kinds == set(shared["node_type"]["enum"])
    assert not reference_kinds & other_kinds
    assert reference_kinds | other_kinds == set(before["$defs"]["KnowledgeV1_nodeType"]["enum"])
    for reference in references:
        (kind,) = reference["properties"]["node_type"]["enum"]
        prefix = knowledge_node_id_prefix(KnowledgeNodeType(kind))
        pattern = reference["properties"]["node_id"]["pattern"]
        assert pattern.startswith("^" + prefix)
        assert pattern.removeprefix("^" + prefix) == shared["node_id"]["pattern"].split(")_", 1)[1]
    assert other["properties"]["node_id"] == original["properties"]["node_id"]
    for branch in branches:
        assert branch["additionalProperties"] is False
        assert branch["required"] == original["required"]
        assert set(branch["properties"]) == set(original["properties"])
        for name in set(original["properties"]) - {"node_id", "node_type"}:
            assert branch["properties"][name] == original["properties"][name]
    assert owner.load_codex_result_schema(SCHEMA) == snapshot
    owner.validate_codex_structured_output_schema(schema)
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    "alias", ["knode_element_eq_ga", "knode_choice_1", "knode_item_element_" + "a" * 33]
)
def test_actual_invalid_aliases_fail_both_model_schema_and_contextual_receiver_but_not_history(
    alias,
):
    parsed, value = sample()
    value["output"]["proposal"]["nodes"][1]["node_id"] = alias
    assert owner.validate_role_result(value, "support", SCHEMA)  # Released Generic1 remains broad.
    schema = owner.constrained_result_schema(SCHEMA, parsed)
    assert list(Draft202012Validator(schema).iter_errors(value))
    with pytest.raises(owner.WorkflowSchemaError, match="nodes"):
        owner.validate_role_result_for_request(value, "support", SCHEMA, parsed)
    assert value["output"]["proposal"]["nodes"][1]["node_id"] == alias


@pytest.mark.parametrize(
    "node_type",
    [
        "CONCEPT",
        "CLAIM",
        "PROCESS",
        "OBSERVABLE_PROPERTY",
        "FORMULA",
        "ITEM_ELEMENT",
        "ASSESSMENT_PATTERN",
    ],
)
def test_each_reference_type_accepts_its_existing_canonical_prefix(node_type):
    parsed, value = sample()
    value["output"]["proposal"]["nodes"][1].update(
        node_type=node_type, node_id="knode_" + node_type.lower() + "_source"
    )
    assert not list(
        Draft202012Validator(owner.constrained_result_schema(SCHEMA, parsed)).iter_errors(value)
    )
    assert owner.validate_role_result_for_request(value, "support", SCHEMA, parsed)


@pytest.mark.parametrize(
    "node_type",
    load_catalog_schema("knowledge-analysis-solution-types-v1")["$defs"]["typedReferenceNode"][
        "properties"
    ]["node_type"]["enum"],
)
def test_declared_reference_type_cannot_use_another_valid_type_prefix(node_type):
    parsed, value = sample()
    other_type = "CONCEPT" if node_type != "CONCEPT" else "ITEM_ELEMENT"
    node_id = knowledge_node_id_prefix(KnowledgeNodeType(other_type)) + "source"
    value["output"]["proposal"]["nodes"][1].update(node_type=node_type, node_id=node_id)
    assert owner.validate_role_result(value, "support", SCHEMA)
    with pytest.raises(ValidationError):
        KnowledgeAnalysisBaseReferenceNode.model_validate(
            {"node_id": node_id, "node_type": node_type}
        )
    assert list(
        Draft202012Validator(owner.constrained_result_schema(SCHEMA, parsed)).iter_errors(value)
    )
    with pytest.raises(owner.WorkflowSchemaError, match="nodes"):
        owner.validate_role_result_for_request(value, "support", SCHEMA, parsed)


@pytest.mark.parametrize("node_type", ["ITEM_REVISION", "TABLE", "FIGURE", "DOCUMENT_REVISION"])
def test_nonreference_nodes_keep_the_generic_identity_contract(node_type):
    parsed, value = sample()
    value["output"]["proposal"]["nodes"][1].update(node_type=node_type, node_id="knode_choice_1")
    schema = owner.constrained_result_schema(SCHEMA, parsed)
    assert not list(Draft202012Validator(schema).iter_errors(value))
    assert owner.validate_role_result_for_request(value, "support", SCHEMA, parsed)


def test_model_and_receiver_use_identical_source_aware_composition():
    parsed, value = sample()
    expected = owner.constrained_result_schema(SCHEMA, parsed)
    compose = owner.constrained_result_schema
    with patch.object(owner, "constrained_result_schema", wraps=compose) as called:
        returned = owner.validate_role_result_for_request(value, "support", SCHEMA, parsed)
    called.assert_called_once_with(SCHEMA, parsed)
    assert returned == owner.validate_role_result(value, "support", SCHEMA)
    assert expected == compose(SCHEMA, parsed)


def test_past_exam_request2_and_document_request3_do_not_gain_registered_item_branches():
    parsed, value = sample()
    request_value = parsed.request.analysis_request.model_dump(mode="json")
    request_value["source"]["source_class"] = "PAST_EXAM"
    request_value["request_sha256"] = content_sha256(
        {key: field for key, field in request_value.items() if key != "request_sha256"}
    )
    other = worker_input(KnowledgeAnalysisRequestV2.model_validate(request_value))
    value["output"]["proposal"]["nodes"][1]["node_id"] = "knode_choice_1"
    for selected in (other, parsed.model_copy(update={"role": "review"})):
        with patch.object(
            owner, "constrained_result_schema", side_effect=AssertionError("Not applicable")
        ):
            assert owner.validate_role_result_for_request(value, "support", SCHEMA, selected)
    assert (
        "$ref"
        in owner.constrained_result_schema(SCHEMA, other)["$defs"][
            "KnowledgeAnalysisWorkerProposal"
        ]["properties"]["nodes"]["items"]
    )
    from eom_catalog_contracts import KnowledgeAnalysisRequestV3

    document = worker_input(KnowledgeAnalysisRequestV3.model_validate(request_v3()))
    document_value = result(
        document, proposal_v3(document.request.analysis_request), protocol="workflow-role/1.5.0"
    )
    with patch.object(
        owner, "constrained_result_schema", side_effect=AssertionError("Not applicable")
    ):
        assert owner.validate_role_result_for_request(
            document_value, "support", "knowledge-analysis-proposal-result@2.0", document
        )


def test_actual_orchestrator_validates_the_context_before_proposal_artifact_commit():
    path = Path(__file__).parents[2] / "services/orchestrator/eom_orchestrator/orchestrator.py"
    module = ast.parse(path.read_text())
    calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    contextual = next(node for node in calls if node.func.id == "validate_role_result_for_request")
    generation = next(node for node in calls if node.func.id == "constrained_result_schema")
    assert isinstance(generation.args[1], ast.Name) and generation.args[1].id == "worker_input"
    assert isinstance(contextual.args[3], ast.Name) and contextual.args[3].id == "worker_input"
    assert contextual.lineno < min(
        node.lineno for node in calls if node.func.id == "stage_knowledge_analysis_proposal"
    )
