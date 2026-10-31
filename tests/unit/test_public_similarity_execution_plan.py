"""Public plan30/31 preserve exact Evidence and released legacy plan meanings."""

from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_delivery import parse_public_solution_similarity_delivery
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, load_control_schema
from eom_workflow.public_similarity_control import (
    PreparedPublicSimilarityPlan,
    ResolvedExecutionPlanV30,
    ResolvedExecutionPlanV31,
    bind_public_similarity_execution_plan,
    parse_public_similarity_execution_plan,
    select_public_similarity_evidence_source,
    validate_public_similarity_original_source,
    validate_public_similarity_plan_context,
)
from eom_workflow.similarity_control import parse_supported_similarity_execution_plan
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.public_similarity_plan_fixtures import public_plan_case
from tests.unit.test_public_solution_delivery import public_delivery_body


@pytest.fixture(params=((False, False), (False, True), (True, False), (True, True)))
def case(tmp_path, monkeypatch, request):
    ordinary, registered = request.param
    return public_plan_case(tmp_path, monkeypatch, ordinary=ordinary, registered=registered)


def test_public_successor_keeps_evidence_controls_steps_and_source_without_old_profile_relabelling(
    case,
):
    plan, base, context = case["plan"], case["base"], case["context"]
    assert isinstance(plan, ResolvedExecutionPlanV30 | ResolvedExecutionPlanV31)
    assert plan.steps == base.steps
    assert plan.graph_snapshot == base.graph_snapshot
    assert plan.retrieval_requirement == base.retrieval_requirement
    assert plan.evidence_manifest_artifact == base.evidence_manifest_artifact
    assert plan.evidence_context_artifact == base.evidence_context_artifact
    assert plan.similarity_delivery.schema_version == "system-rag-similarity-delivery/2.0"
    assert validate_public_similarity_plan_context(plan, context) == context
    assert parse_public_similarity_execution_plan(plan) == plan
    preparation = PreparedPublicSimilarityPlan(case["delivery"], context)
    preparation.__post_init__()
    original = context.request.anchor.source
    assert select_public_similarity_evidence_source(plan, (original,)) == original
    validate_public_similarity_original_source(plan, context, original)
    assert case["base"].schema_version == "resolved-execution-plan/19.0"
    assert canonical_json_bytes(plan) != canonical_json_bytes(base)
    with pytest.raises((ValueError, SchemaError)):
        parse_supported_similarity_execution_plan(plan)


@pytest.mark.parametrize("fault", ("purpose", "source", "graph", "policy", "report"))
def test_rehashed_foreign_context_is_not_a_new_authority_or_latest_substitute(case, fault):
    body = case["context"].model_dump(mode="json")
    request = body["request"]
    if fault == "purpose":
        request["consumer_purpose"] = "ITEM_REVIEW"
    elif fault == "source":
        request["anchor"]["source"]["item_revision_id"] = "itemrev_" + "0" * 32
    elif fault == "graph":
        request["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
    elif fault == "policy":
        request["policy_sha256"] = "sha256:" + "0" * 64
    else:
        request["anchor"]["evidence"]["solution"]["solution_result_sha256"] = "sha256:" + "0" * 64
        request["anchor"]["evidence"]["solution"] = seal(
            request["anchor"]["evidence"]["solution"], "pointer_sha256"
        )
    body["request"] = seal(request, "request_sha256")
    foreign = parse_supported_public_solution_similarity_context(seal(body, "context_sha256"))
    with pytest.raises((ValueError, SchemaError)):
        validate_public_similarity_plan_context(case["plan"], foreign)
    if fault in {"purpose", "source", "graph", "policy"}:
        pin = parse_public_solution_similarity_delivery(public_delivery_body(foreign))
        if fault == "source" and isinstance(case["plan"], ResolvedExecutionPlanV31):
            # A fresh ordinary candidate may choose a different approved reference.
            # Original Evidence membership is independently checked at staging.
            candidate = bind_public_similarity_execution_plan(case["base"], pin, foreign)
            with pytest.raises(ValueError):
                select_public_similarity_evidence_source(
                    candidate, (case["context"].request.anchor.source,)
                )
        else:
            with pytest.raises((ValueError, SchemaError)):
                bind_public_similarity_execution_plan(case["base"], pin, foreign)


@pytest.mark.parametrize(
    "fault", ("hash", "extra", "missing", "legacy_delivery", "no_evidence", "bool")
)
def test_new_plan_is_closed_and_raw_forged_values_are_not_erased(case, fault):
    body = case["plan"].model_dump(mode="json")
    if fault == "hash":
        body["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "extra":
        body = case["plan"].model_copy(update={"authority": "ADMIN"})
    elif fault == "missing":
        body.pop("similarity_delivery")
    elif fault == "legacy_delivery":
        body["similarity_delivery"]["schema_version"] = "system-rag-similarity-delivery/1.0"
    elif fault == "bool":
        body["steps"][0]["timeout_seconds"] = True
    else:
        body["steps"][0]["evidence_access"] = "NONE"
        body = seal(body, "plan_sha256")
    with pytest.raises((ValueError, SchemaError)):
        parse_public_similarity_execution_plan(body)


@pytest.mark.parametrize("fault", ("missing", "duplicate", "member", "revision"))
def test_exact_evidence_source_is_still_required(case, fault):
    source = case["context"].request.anchor.source
    if fault == "missing":
        values = ()
    elif fault == "duplicate":
        values = (source, source)
    elif fault == "revision":
        values = (source.model_copy(update={"item_revision_id": "itemrev_" + "0" * 32}),)
    else:
        altered = source.artifact_member.model_copy(update={"sha256": "sha256:" + "0" * 64})
        values = (source.model_copy(update={"artifact_member": altered}),)
    with pytest.raises((ValueError, SchemaError)):
        if fault == "member" and isinstance(case["plan"], ResolvedExecutionPlanV30):
            validate_public_similarity_original_source(case["plan"], case["context"], values[0])
        else:
            select_public_similarity_evidence_source(case["plan"], values)


@pytest.mark.parametrize("status", ("PARTIAL", "EMPTY"))
def test_public_plan_keeps_coverage_limits_not_false_complete(case, status):
    body = case["context"].model_dump(mode="json")
    body["status"] = status
    if status == "PARTIAL":
        body["population"]["authorized_source_count"] += 1
        body["limitations"].append("PARTIAL_REPORT_COVERAGE")
    else:
        body["population"]["scored_count"] = 0
        body["candidates"] = []
    context = parse_supported_public_solution_similarity_context(seal(body, "context_sha256"))
    pin = parse_public_solution_similarity_delivery(public_delivery_body(context))
    plan = bind_public_similarity_execution_plan(case["base"], pin, context)
    assert validate_public_similarity_plan_context(plan, context).status == status


def test_schema_mirrors_and_released_predecessor_bytes_are_frozen():
    root = Path(__file__).resolve().parents[2]
    for version in (30, 31):
        entry = CONTROL_SCHEMA_RESOURCES[f"resolved-execution-plan-v{version}"]
        raw = (root / entry.canonical_path).read_bytes()
        assert raw == (root / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
        assert sha256_bytes(raw) == entry.sha256
        Draft202012Validator.check_schema(
            load_control_schema(f"resolved-execution-plan-v{version}")
        )
    for version, digest in (
        (23, "d0d41a79fee8d94c7815795081f55f46696e2802623670d09491559afefb02ad"),
        (24, "21c49d6a0a7e2a46ef0eca5cb02e1d4ac5f4685d692f1b27b577a13c334f699b"),
    ):
        raw = (
            root / f"schemas/workflow/control-plane/resolved-execution-plan-v{version}.schema.json"
        ).read_bytes()
        assert sha256_bytes(raw) == "sha256:" + digest
