from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from eom_catalog_contracts import (
    ContentTeamMaterialRequirementV2,
    EducationalRetrievalRequirementV2,
    PastExamVariationRequest,
    derive_content_team_material_requirement_v2,
)
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import ContentPackError, WorkflowCatalogService
from eom_hwpx_contracts import ContentTeamImageSlot
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError, ResolvedPlanDependencyEvidence
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    resolve_execution_plan,
    resolve_knowledge_backed_execution_plan,
)
from eom_workflow import (
    WORKFLOW_ADMISSION_BY_IDENTITY,
    ResolvedExecutionPlanV17,
    ResolvedExecutionPlanV18,
    compile_definition,
    validate_control_contract,
)
from eom_workflow.control_plane import WorkerRole
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.engine import _parse_review_escalation_plan

from tests.unit.test_content_team_v3_protocol import _content_v3
from tests.unit.test_execution_resolver import FakeSession, _bundle
from tests.unit.test_knowledge_backed_execution import (
    NOW,
    _evidence,
    _requirement,
    _Session,
    _verification_preset,
)

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.11"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.12"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_natural_presentation_workflow_and_pack_form_one_immutable_successor() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(SUCCESSOR)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("fixtures/smoke-request.json"),
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
    }

    workflow = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.15.yaml",
        {"authoring", "image", "review", "item_management"},
    ).definition
    pack = compile_pack(SUCCESSOR)
    request = WorkflowRequest.model_validate_json(
        (SUCCESSOR / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    authoring_profile = yaml.safe_load(
        (SUCCESSOR / "profiles/generated-knowledge-authoring.yaml").read_text(encoding="utf-8")
    )
    review_profile = yaml.safe_load(
        (SUCCESSOR / "profiles/generated-knowledge-review.yaml").read_text(encoding="utf-8")
    )

    assert workflow.definition_version == "1.15.0"
    assert workflow.limits.max_rework_cycles == 3
    assert (
        WORKFLOW_ADMISSION_BY_IDENTITY[("generic-item-development", "1.15.0")].role_protocol_version
        == "workflow-role/1.24.0"
    )
    assert pack.manifest.pack.version == "1.20.12"
    assert pack.manifest.compatibility.workflow_definitions[0].versions == ("1.15.0",)
    assert authoring_profile["profile"]["version"] == "12.2.0"
    assert review_profile["profile"]["version"] == "12.2.0"
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.12", request
    )


def test_natural_presentation_pack_rejects_predecessor_brief_family() -> None:
    predecessor_request = WorkflowRequest.model_validate_json(
        (PREDECESSOR / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    successor_request = WorkflowRequest.model_validate_json(
        (SUCCESSOR / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ContentPackError, match="material-aware item brief"):
        WorkflowCatalogService._require_item_brief_release(
            "generated-knowledge-item", "1.20.12", predecessor_request
        )
    with pytest.raises(ContentPackError, match="material-aware item brief"):
        WorkflowCatalogService._require_item_brief_release(
            "generated-knowledge-item", "1.20.11", successor_request
        )


def test_catalog_binds_v5_variation_to_exact_source_presentation() -> None:
    request = WorkflowRequest.model_validate_json(
        (SUCCESSOR / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    assert request.item_brief is not None
    source_revision_id = "itemrev_" + "4" * 32
    source = _content_v3(
        visuals=(ContentTeamImageSlot(),),
        visual_layout="IMAGE_ONLY",
    )
    expected = derive_content_team_material_requirement_v2(source)
    retrieval = EducationalRetrievalRequirementV2(
        corpus_key="integrated-science-textbooks",
        required_item_elements=("choice", "image", "paragraph"),
        past_exam_variation=PastExamVariationRequest(
            source_item_revision_id=source_revision_id,
            variation_axes=("CONTEXT", "DISTRACTORS", "REASONING_PATH", "VALUES"),
        ),
    )
    exact = WorkflowRequest.model_validate(
        request.model_dump(mode="json")
        | {
            "image_mode": "required",
            "execution_preset_key": "knowledge-grounded-item",
            "educational_retrieval": retrieval.model_dump(mode="json"),
            "item_brief": request.item_brief.model_dump(mode="json")
            | {"material_requirement": expected.model_dump(mode="json")},
        }
    )
    service = SimpleNamespace(
        registry=SimpleNamespace(load_item_content=lambda _revision_id: source)
    )

    WorkflowCatalogService._require_v5_source_presentation(service, exact)  # type: ignore[arg-type]

    mismatched = exact.model_copy(
        update={
            "item_brief": exact.item_brief.model_copy(  # type: ignore[union-attr]
                update={
                    "material_requirement": ContentTeamMaterialRequirementV2(
                        form="IMAGE",
                        panel_count=1,
                        image_supporting_data="LABELED_DATA",
                    )
                }
            )
        }
    )
    with pytest.raises(ContentPackError, match="exact past-exam source"):
        WorkflowCatalogService._require_v5_source_presentation(  # type: ignore[arg-type]
            service,
            mismatched,
        )


def test_natural_presentation_prompts_close_labeled_data_and_variation_boundaries() -> None:
    authoring = (SUCCESSOR / "prompt-templates/authoring.md").read_text(encoding="utf-8")
    review = (SUCCESSOR / "prompt-templates/review.md").read_text(encoding="utf-8")
    for required in (
        "image_supporting_data=NONE",
        "DATA block은\n  정확히 0개",
        "image_supporting_data=LABELED_DATA",
        "빈 두 번째 칸",
        "<자료>",
        "source-item.json`이 materialize된 exact",
    ):
        assert required in authoring
    for required in (
        "image_supporting_data=NONE",
        "MATERIAL_PRESENTATION_REDUNDANT",
        "literal `<자료>`",
        "source-item.json`이 materialize된 exact",
    ):
        assert required in review


def test_v17_plan_pins_general_retrieval_to_workflow_115(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _verification_preset()
    evidence = _evidence(manifest_schema_version="5.0")
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.15.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.24.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
        graph_snapshot_revision_id=evidence.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=evidence.evidence_bundle_revision_id,
    )
    captured: dict[str, Any] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        captured.update(document)
        assert dependencies is not None
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    plan = resolve_knowledge_backed_execution_plan(
        _Session(preset),  # type: ignore[arg-type]
        preset_revision_id=preset.preset_revision_id,
        requirement=_requirement(),
        evidence=evidence,
        dependencies=dependencies,
        steps=(
            ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),
            ExecutionStepRequirement("review", WorkerRole.REVIEW),
        ),
        resolved_at=NOW,
    )

    assert isinstance(plan, ResolvedExecutionPlanV17)
    assert plan.schema_version == "resolved-execution-plan/17.0"
    assert plan.resolver_version == "17.0.0"
    assert plan.workflow_definition_version == "1.15.0"
    assert plan.plan_sha256 == content_sha256(
        {key: value for key, value in captured.items() if key != "plan_sha256"}
    )


def _ungrounded_verification_preset() -> dict[str, Any]:
    policies = []
    for index, role in enumerate(("authoring", "image", "review", "item_management"), start=1):
        candidates = [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}]
        if role == "review":
            candidates.append({"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"})
        policies.append(
            {
                "role": role,
                "model_candidates": candidates,
                "instruction_bundle": _bundle(str(index), family="instr"),
                "reference_bundle": None,
                "worker_pool_key": role.replace("item_management", "item-management"),
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
            }
        )
    document: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "5" * 32,
        "preset_revision_id": "execpresetrev_" + "6" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "Ungrounded verification",
        "description": "Pins one stronger review candidate without Evidence Bundle access.",
        "role_policies": policies,
        "capacity_policy_revision_id": "capacityrev_" + "7" * 32,
        "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
        "compatible_workflow_protocols": ["workflow-role/1.24.0"],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "content_sha256"}
    )
    return document


def test_v18_plan_pins_ungrounded_primary_and_escalated_review_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _ungrounded_verification_preset()
    logical = SimpleNamespace(
        state="ACTIVE",
        current_revision_id=preset["preset_revision_id"],
        preset_id=preset["preset_id"],
    )
    revision = SimpleNamespace(
        preset_id=preset["preset_id"],
        state="RELEASED",
        canonical_document=preset,
    )
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "8" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.15.0",
        workflow_definition_sha256="sha256:" + "9" * 64,
        workflow_role_schema_version="workflow-role/1.24.0",
        content_pack_release_id="packrel_" + "a" * 32,
        content_pack_sha256="sha256:" + "b" * 64,
    )
    captured: dict[str, Any] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        captured.update(document)
        assert dependencies is not None
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_resolved_execution_plan", record
    )
    plan = resolve_execution_plan(
        FakeSession([None, logical], revision),  # type: ignore[arg-type]
        preset_key="standard-item",
        dependencies=dependencies,
        steps=tuple(
            ExecutionStepRequirement(step_key, role)
            for step_key, role in (
                ("authoring", WorkerRole.AUTHORING),
                ("image", WorkerRole.IMAGE),
                ("review", WorkerRole.REVIEW),
                ("item_management", WorkerRole.ITEM_MANAGEMENT),
            )
        ),
        resolved_at=NOW,
    )

    assert isinstance(plan, ResolvedExecutionPlanV18)
    assert plan.schema_version == "resolved-execution-plan/18.0"
    assert plan.graph_snapshot_revision_id is None
    assert plan.evidence_bundle_revision_id is None
    assert all(step.evidence_access == "NONE" for step in plan.steps)
    review = next(step for step in plan.steps if step.role == WorkerRole.REVIEW)
    assert review.escalation_candidate is not None
    assert review.escalation_candidate.model == "gpt-5.6-sol"
    validate_control_contract("resolved-execution-plan-v18", plan.model_dump(mode="json"))
    assert _parse_review_escalation_plan(plan.model_dump(mode="json")) == plan
    assert plan.plan_sha256 == content_sha256(
        {key: value for key, value in captured.items() if key != "plan_sha256"}
    )


def test_v18_plan_rejects_missing_review_escalation_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _ungrounded_verification_preset()
    review = next(policy for policy in preset["role_policies"] if policy["role"] == "review")
    review["model_candidates"] = review["model_candidates"][:1]
    preset["content_sha256"] = content_sha256(
        {key: value for key, value in preset.items() if key != "content_sha256"}
    )
    logical = SimpleNamespace(
        state="ACTIVE",
        current_revision_id=preset["preset_revision_id"],
        preset_id=preset["preset_id"],
    )
    revision = SimpleNamespace(
        preset_id=preset["preset_id"], state="RELEASED", canonical_document=preset
    )
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.15.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.24.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
    )
    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_resolved_execution_plan",
        lambda *_args, **_kwargs: pytest.fail("invalid plan must not be persisted"),
    )

    with pytest.raises(ControlPlaneError, match="candidate cardinality"):
        resolve_execution_plan(
            FakeSession([None, logical], revision),  # type: ignore[arg-type]
            preset_key="standard-item",
            dependencies=dependencies,
            steps=(ExecutionStepRequirement("review", WorkerRole.REVIEW),),
            resolved_at=NOW,
        )
