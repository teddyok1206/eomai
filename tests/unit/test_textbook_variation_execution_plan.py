"""New variation controls reuse released workflow/role/materialization without old-byte edits."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import resolve_integrated_science_curriculum_scope
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.execution_resolver import resolve_knowledge_backed_execution_plan
from eom_workflow.control_plane import ResolvedExecutionPlanV19, ResolvedExecutionPlanV35
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, validate_control_contract
from eom_workflow.models import WorkflowRequest
from eom_workflow.public_similarity_control import (
    PreparedPublicSimilarityPlan,
    ResolvedExecutionPlanV36,
    bind_public_similarity_execution_plan,
    select_public_similarity_evidence_source,
    validate_public_similarity_plan_context,
)
from eom_workflow.similarity_control import parse_post_registration_grounded_plan
from eom_workflow_runner.engine import _parse_review_escalation_plan
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.public_similarity_materialization_fixtures import public_materialization_case
from tests.unit.public_similarity_plan_fixtures import public_plan_case
from tests.unit.test_execution_materializer import GROUP_ID, _workspace
from tests.unit.test_knowledge_backed_execution import _Session
from tests.unit.test_public_similarity_plan_resolution import ReplaySession
from tests.unit.test_similarity_plan_execution_binding import creation_arguments
from tests.unit.textbook_variation_plan_fixtures import textbook_variation_base


@pytest.mark.parametrize("fault", (None, "missing_scope", "different_root"))
def test_variation_inherited_source_guard_does_not_bypass_curriculum_root(
    tmp_path, monkeypatch, fault
):
    case = public_plan_case(tmp_path, monkeypatch)
    requirement = textbook_variation_base(case["base"]).retrieval_requirement
    root = Path(__file__).resolve().parents[2]
    body = json.loads(
        (
            root / "content/packs/generated-knowledge-item/1.20.18/fixtures/smoke-request.json"
        ).read_text(encoding="utf-8")
    )
    body["execution_preset_key"] = "knowledge-grounded-item"
    body["educational_retrieval"] = requirement.model_dump(mode="json")
    body["item_brief"]["curriculum_scope"] = resolve_integrated_science_curriculum_scope(
        "eom.is.middle.1-1"
    ).model_dump(mode="json")
    if fault == "missing_scope":
        body["item_brief"]["curriculum_scope"] = None
    elif fault == "different_root":
        body["educational_retrieval"]["curriculum_root_key"] = "curriculum.foreign-root"
    if fault is None:
        assert WorkflowRequest.model_validate(body).educational_retrieval == requirement
    else:
        with pytest.raises(ValueError, match="selected curriculum graph root"):
            WorkflowRequest.model_validate(body)


@pytest.mark.parametrize("with_similarity", (False, True))
def test_new_variation_resolves_once_and_replays_original_pins(
    tmp_path, monkeypatch, with_similarity
):
    case = public_plan_case(tmp_path, monkeypatch, registered=True)
    old_base = case["base"]
    case["base"] = textbook_variation_base(old_base)
    arguments, preset = creation_arguments(case)
    recorded = []

    def record(session, *, document, dependencies):
        version = 36 if with_similarity else 35
        validate_control_contract(f"resolved-execution-plan-v{version}", document)
        recorded.append(document)
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    prepared = (
        PreparedPublicSimilarityPlan(case["delivery"], case["context"]) if with_similarity else None
    )
    plan = resolve_knowledge_backed_execution_plan(
        _Session(preset), **arguments, similarity=prepared
    )
    assert isinstance(
        plan, ResolvedExecutionPlanV36 if with_similarity else ResolvedExecutionPlanV35
    )
    assert len(recorded) == 1
    assert plan.workflow_definition_version == "1.16.0"
    assert plan.retrieval_requirement.source_classes == ("PAST_EXAM", "TEXTBOOK")
    assert plan.retrieval_requirement.past_exam_variation == (
        old_base.retrieval_requirement.past_exam_variation
    )
    assert plan.evidence_manifest_artifact == old_base.evidence_manifest_artifact
    assert parse_post_registration_grounded_plan(plan.model_dump(mode="json")) == plan
    assert _parse_review_escalation_plan(plan.model_dump(mode="json")) == plan
    assert (
        resolve_knowledge_backed_execution_plan(
            ReplaySession(plan), **arguments, similarity=prepared
        )
        == plan
    )
    assert len(recorded) == 1
    assert old_base.schema_version == "resolved-execution-plan/19.0"


def test_new_requirement_cannot_be_relabelled_as_old_plan_or_older_workflow(tmp_path, monkeypatch):
    case = public_plan_case(tmp_path, monkeypatch)
    case["base"] = textbook_variation_base(case["base"])
    body = case["base"].model_dump(mode="json")
    body.update(schema_version="resolved-execution-plan/19.0", resolver_version="19.0.0")
    with pytest.raises((ValueError, SchemaError)):
        ResolvedExecutionPlanV19.model_validate(seal(body, "plan_sha256"))
    arguments, preset = creation_arguments(case)
    arguments["dependencies"] = replace(
        arguments["dependencies"], workflow_definition_version="1.15.0"
    )
    with pytest.raises(ControlPlaneError) as error:
        resolve_knowledge_backed_execution_plan(_Session(preset), **arguments)
    assert error.value.code == "CONTROL_VARIATION_PROTOCOL_MISMATCH"


@pytest.mark.parametrize("fault", ("target", "graph", "root_missing", "past_only", "extra"))
def test_successor_rejects_mismatched_reference_or_incomplete_grounding(
    tmp_path, monkeypatch, fault
):
    case = public_plan_case(tmp_path, monkeypatch)
    base = textbook_variation_base(case["base"])
    body = base.model_dump(mode="json")
    requirement = body["retrieval_requirement"]
    if fault == "target":
        requirement["past_exam_variation"]["source_item_revision_id"] = "itemrev_" + "0" * 32
    elif fault == "graph":
        body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
    elif fault == "root_missing":
        requirement["curriculum_root_key"] = None
    elif fault == "past_only":
        requirement["source_classes"] = ["PAST_EXAM"]
    else:
        body["authority"] = "ADMIN"
    body["retrieval_requirement_sha256"] = content_sha256(requirement)
    with pytest.raises((ValueError, SchemaError)):
        candidate = parse_post_registration_grounded_plan(seal(body, "plan_sha256"))
        bind_public_similarity_execution_plan(candidate, case["delivery"], case["context"])


@pytest.mark.parametrize("role,tier", (("authoring", "PRIMARY"), ("review", "ESCALATED")))
@pytest.mark.parametrize("with_similarity", (False, True))
def test_successor_uses_same_exact_source_and_existing_public_materialization(
    tmp_path, monkeypatch, role, tier, with_similarity
):
    case = public_materialization_case(tmp_path, monkeypatch, registered=True)
    base = textbook_variation_base(case["base"])
    plan = (
        bind_public_similarity_execution_plan(base, case["delivery"], case["context"])
        if with_similarity
        else base
    )
    bound = case["bound"] if with_similarity else None
    if with_similarity:
        assert isinstance(plan, ResolvedExecutionPlanV36)
        assert validate_public_similarity_plan_context(plan, case["context"]) == case["context"]
        original = case["context"].request.anchor.source
        assert select_public_similarity_evidence_source(plan, (original,)) == original
    record = case["session"].records[(ResolvedExecutionPlanRecord, case["plan_id"])]
    record.canonical_document = plan.model_dump(mode="json")
    record.plan_sha256 = plan.plan_sha256
    record.workflow_id = plan.workflow_id
    allowlist = authorized_execution_artifact_revisions(
        case["session"], plan_id=plan.plan_id, step_key=role, similarity_context=bound
    )
    workspace = _workspace(tmp_path, "textbook-variation")
    materialize_execution_step(
        case["session"],
        plan_id=plan.plan_id,
        step_key=role,
        workspace=workspace,
        canonical_artifact_root=case["artifact_root"],
        worker_group_id=GROUP_ID,
        authorized_artifact_revision_ids=allowlist,
        similarity_context=bound,
        execution_tier=tier,
    )
    assert (workspace / "references/variation/source-item.json").read_bytes() == case[
        "source_payload"
    ]
    assert (workspace / "references/evidence/context.md").read_bytes() == case["context_payload"]
    if with_similarity:
        assert (workspace / "references/similarity/context.json").read_bytes() == case[
            "payload"
        ].context_payload
    else:
        assert not (workspace / "references/similarity").exists()


def test_new_schema_resources_are_packaged_and_old_plan_bytes_remain_frozen():
    root = Path(__file__).resolve().parents[2]
    for version in (35, 36):
        resource = CONTROL_SCHEMA_RESOURCES[f"resolved-execution-plan-v{version}"]
        raw = (root / resource.canonical_path).read_bytes()
        assert (
            raw == (root / "packages/workflow/eom_workflow" / resource.resource_path).read_bytes()
        )
        assert sha256_bytes(raw) == resource.sha256
    for version, sha in (
        (30, "601afd4b1b2648cca68a51efb6e7d60315f726aac7373920d840bbf932f8db4c"),
        (31, "016f9b2c0d4872f21b387f71f0f126f5ebda9c0e668915060d99915d8d60eee3"),
        (32, "337a03c4cd28ec3f3a486f1b0d99d4cd934fbac0a9887304a1c7efa182a8cac3"),
        (33, "4d877271f144c8318201b1a4c589de75b0376aec179338d2555f9892dc827279"),
    ):
        resource = CONTROL_SCHEMA_RESOURCES[f"resolved-execution-plan-v{version}"]
        assert sha256_bytes((root / resource.canonical_path).read_bytes()) == "sha256:" + sha
