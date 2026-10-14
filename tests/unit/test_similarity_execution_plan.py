"""Schema-first auxiliary plan23; original plans/workflow/role bytes remain unchanged."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_delivery import parse_similarity_context_delivery
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    record_knowledge_backed_execution_plan,
)
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, load_control_schema
from eom_workflow.similarity_control import (
    bind_similarity_execution_plan,
    parse_similarity_execution_plan,
    validate_similarity_original_source,
    validate_similarity_plan_context,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import similarity_case
from tests.unit.test_similarity_delivery_contracts import delivery_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def test_new_plan_schema_is_registered_with_exact_mirror_and_offline_refs() -> None:
    entry = CONTROL_SCHEMA_RESOURCES["resolved-execution-plan-v23"]
    raw = (ROOT / entry.canonical_path).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert entry.sha256 == "sha256:d0d41a79fee8d94c7815795081f55f46696e2802623670d09491559afefb02ad"
    Draft202012Validator.check_schema(load_control_schema("resolved-execution-plan-v23"))


def test_unpersisted_base_binds_separate_pin_without_changing_existing_graph_or_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = similarity_case(tmp_path, monkeypatch)
    base, plan, context = case["base"], case["plan"], case["context"]
    assert plan.workflow_definition_version == base.workflow_definition_version == "1.16.0"
    assert plan.steps == base.steps
    assert plan.evidence_manifest_artifact == base.evidence_manifest_artifact
    assert plan.retrieval_requirement == base.retrieval_requirement
    assert plan.plan_sha256 != base.plan_sha256
    assert parse_similarity_execution_plan(plan) == plan
    assert validate_similarity_plan_context(plan, context) == context
    assert bind_similarity_execution_plan(base, case["delivery"], context) == plan
    assert "candidates" not in plan.model_dump()
    validate_similarity_original_source(
        plan, context, TypeAdapter(PopulationSource).validate_python(case["original_source"])
    )
    assert canonical_json_bytes(base.model_dump(mode="json")) != canonical_json_bytes(
        plan.model_dump(mode="json")
    )


@pytest.mark.parametrize("field", ("source", "graph", "policy_revision", "policy_sha", "purpose"))
def test_valid_but_foreign_context_is_not_a_variation_plan_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    case = similarity_case(tmp_path, monkeypatch)
    raw = case["context"].model_dump(mode="json")
    request = raw["request"]
    if field == "source":
        request["anchor"]["source"]["item_revision_id"] = "itemrev_" + "0" * 32
    elif field == "graph":
        request["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
    elif field == "policy_revision":
        request["policy_revision_id"] = "accessrev_" + "0" * 32
    elif field == "policy_sha":
        request["policy_sha256"] = "sha256:" + "0" * 64
    else:
        request["consumer_purpose"] = "GENERAL_CHAT_READ"
    raw["request"] = seal(request, "request_sha256")
    foreign = parse_similarity_context(seal(raw, "context_sha256"))
    delivery = parse_similarity_context_delivery(delivery_body(foreign))
    with pytest.raises(ValueError, match="CONTEXT_MISMATCH"):
        bind_similarity_execution_plan(case["base"], delivery, foreign)


@pytest.mark.parametrize(
    "fault",
    ("hash", "copied_extra", "bool_timeout", "missing_pin", "no_authoring", "no_reference_access"),
)
def test_plan_raw_corruption_is_rejected_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    case = similarity_case(tmp_path, monkeypatch)
    plan = case["plan"]
    raw: Any = plan.model_dump(mode="json")
    if fault == "hash":
        raw["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "copied_extra":
        raw = plan.model_copy(update={"role": "ADMIN"})
    elif fault == "bool_timeout":
        raw["steps"][0]["timeout_seconds"] = True
    elif fault == "missing_pin":
        raw.pop("similarity_delivery")
    elif fault == "no_authoring":
        raw["steps"][0]["role"] = "image"
        raw = seal(raw, "plan_sha256")
    else:
        raw["steps"][0]["evidence_access"] = "NONE"
        raw = seal(raw, "plan_sha256")
    with pytest.raises(ERRORS):
        parse_similarity_execution_plan(raw)


def test_new_plan_persistence_keeps_dependency_guard_before_any_db_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = similarity_case(tmp_path, monkeypatch)
    plan = case["plan"]

    class NoAccessSession:
        def __getattr__(self, name):
            raise AssertionError(f"unexpected persistence access: {name}")

    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "0" * 32,
        workflow_definition_key=plan.workflow_definition_key,
        workflow_definition_version=plan.workflow_definition_version,
        workflow_definition_sha256=plan.workflow_definition_sha256,
        workflow_role_schema_version="workflow-role/1.24.0",
        content_pack_release_id=plan.content_pack_release_id,
        content_pack_sha256=plan.content_pack_sha256,
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=plan.evidence_bundle_revision_id,
    )
    with pytest.raises(ControlPlaneError) as captured:
        record_knowledge_backed_execution_plan(
            NoAccessSession(),  # type: ignore[arg-type]
            document=plan.model_dump(mode="json"),
            dependencies=dependencies,
        )
    assert captured.value.code == "CONTROL_PLAN_DEPENDENCY_MISMATCH"
