"""Ordinary-reference plan successor; no model/current IAM is fabricated by these values."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_delivery import parse_similarity_context_delivery
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, load_control_schema
from eom_workflow.similarity_control import (
    ResolvedExecutionPlanV24,
    bind_authoring_similarity_execution_plan,
    bind_similarity_execution_plan,
    parse_authoring_similarity_execution_plan,
    parse_post_registration_grounded_plan,
    parse_similarity_execution_plan,
    select_similarity_evidence_source,
    validate_similarity_plan_context,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import ordinary_similarity_case, similarity_case
from tests.unit.test_similarity_delivery_contracts import delivery_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def test_ordinary_plan_schema_has_exact_mirror_and_pinned_offline_registry() -> None:
    entry = CONTROL_SCHEMA_RESOURCES["resolved-execution-plan-v24"]
    raw = (ROOT / entry.canonical_path).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert entry.sha256 == "sha256:21c49d6a0a7e2a46ef0eca5cb02e1d4ac5f4685d692f1b27b577a13c334f699b"
    Draft202012Validator.check_schema(load_control_schema("resolved-execution-plan-v24"))


def test_ordinary_reference_binding_preserves_requirement_evidence_and_review_steps(
    tmp_path, monkeypatch
):
    case = ordinary_similarity_case(tmp_path, monkeypatch)
    plan, base, context = case["plan"], case["base"], case["context"]
    assert type(plan) is ResolvedExecutionPlanV24
    assert plan.retrieval_requirement.schema_version == "educational-retrieval-requirement/1.0"
    assert "past_exam_variation" not in plan.retrieval_requirement.model_dump()
    assert plan.retrieval_requirement == base.retrieval_requirement
    assert plan.evidence_manifest_artifact == base.evidence_manifest_artifact
    assert plan.steps == base.steps
    assert plan.similarity_reference == context.request.anchor
    assert plan.similarity_delivery == case["delivery"]
    assert validate_similarity_plan_context(plan, context) == context
    assert parse_post_registration_grounded_plan(plan.model_dump(mode="json")) == plan
    assert canonical_json_bytes(plan.model_dump(mode="json")) != canonical_json_bytes(
        base.model_dump(mode="json")
    )
    with pytest.raises(ERRORS):
        parse_similarity_execution_plan(plan)
    with pytest.raises(ERRORS):
        bind_similarity_execution_plan(base, case["delivery"], context)


def test_old_variation_plan_is_not_an_ordinary_request(tmp_path, monkeypatch):
    case = similarity_case(tmp_path, monkeypatch)
    with pytest.raises(ERRORS):
        parse_authoring_similarity_execution_plan(case["plan"])
    with pytest.raises(ERRORS):
        bind_authoring_similarity_execution_plan(case["base"], case["delivery"], case["context"])


@pytest.mark.parametrize("fault", ("purpose", "source", "graph", "policy", "report"))
def test_foreign_reference_context_cannot_be_rebound_to_a_pinned_ordinary_plan(
    tmp_path, monkeypatch, fault
):
    case = ordinary_similarity_case(tmp_path, monkeypatch)
    raw = case["context"].model_dump(mode="json")
    request = raw["request"]
    if fault == "purpose":
        request["consumer_purpose"] = "ITEM_REVIEW"
    elif fault == "source":
        request["anchor"]["source"]["item_revision_id"] = "itemrev_" + "0" * 32
    elif fault == "graph":
        request["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
    elif fault == "policy":
        request["policy_revision_id"] = "accessrev_" + "0" * 32
    else:
        request["anchor"]["profile"] = None
        request["anchor"]["solution_evidence"] = None
        for coverage in raw["population"]["views"]:
            coverage["reason"] = "ANCHOR_REPORT_MISSING"
    raw["request"] = seal(request, "request_sha256")
    foreign = parse_similarity_context(seal(raw, "context_sha256"))
    with pytest.raises(ValueError, match=r"MISMATCH|DELIVERY_INVALID"):
        validate_similarity_plan_context(case["plan"], foreign)
    if fault in {"purpose", "graph", "policy"}:
        delivery = parse_similarity_context_delivery(delivery_body(foreign))
        with pytest.raises(ValueError, match="MISMATCH"):
            bind_authoring_similarity_execution_plan(case["base"], delivery, foreign)


@pytest.mark.parametrize("fault", ("missing", "duplicate", "member", "revision"))
def test_ordinary_anchor_must_match_exactly_one_official_evidence_source(
    tmp_path, monkeypatch, fault
):
    case = ordinary_similarity_case(tmp_path, monkeypatch)
    source = TypeAdapter(PopulationSource).validate_python(case["original_source"])
    assert select_similarity_evidence_source(case["plan"], (source,)) == source
    if fault == "missing":
        sources = ()
    elif fault == "duplicate":
        sources = (source, source)
    else:
        raw = source.model_dump(mode="json")
        if fault == "member":
            raw["artifact_member"]["sha256"] = "sha256:" + "0" * 64
        else:
            raw["item_revision_id"] = "itemrev_" + "0" * 32
        sources = (TypeAdapter(PopulationSource).validate_python(raw),)
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        select_similarity_evidence_source(case["plan"], sources)


@pytest.mark.parametrize("fault", ("extra", "hash", "bool", "missing_reference", "no_evidence"))
def test_ordinary_plan_is_closed_and_checked_before_materialization(tmp_path, monkeypatch, fault):
    case = ordinary_similarity_case(tmp_path, monkeypatch)
    raw = case["plan"].model_dump(mode="json")
    if fault == "extra":
        raw = case["plan"].model_copy(update={"authority": "ADMIN"})
    elif fault == "hash":
        raw["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "bool":
        raw["steps"][0]["timeout_seconds"] = True
    elif fault == "missing_reference":
        raw.pop("similarity_reference")
    else:
        raw["steps"][0]["evidence_access"] = "NONE"
        raw = seal(raw, "plan_sha256")
    with pytest.raises(ERRORS):
        parse_authoring_similarity_execution_plan(raw)
