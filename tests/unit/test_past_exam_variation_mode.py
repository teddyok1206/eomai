from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_contracts import (
    EducationalRetrievalRequirementV2,
    EvidenceBundleManifestV5,
    PastExamVariationRequest,
    validate_contract,
)
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ResolvedPlanDependencyEvidence
from eom_orchestrator.evidence_usage_validation import (
    EvidenceUsageValidationError,
    _validate_variation_source_citation,
)
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    resolve_knowledge_backed_execution_plan,
)
from eom_web_gui.contracts import RequestDraftInput, RequestDraftUpdate
from eom_web_gui.request_drafts import normalize_request, update_draft, workflow_start_payload
from eom_workflow import (
    WORKFLOW_ADMISSION_BY_IDENTITY,
    ExecutionPresetRevisionV2,
    ResolvedExecutionPlanV16,
    compile_definition,
)
from eom_workflow.control_plane import WorkerRole
from eom_workflow.models import EvidenceUsageCitationV1, WorkflowRequest
from eom_workflow_runner.engine import _parse_review_escalation_plan
from pydantic import ValidationError

from tests.unit.test_execution_materializer import _past_exam_variation_fixture
from tests.unit.test_knowledge_backed_execution import (
    NOW,
    _evidence,
    _Session,
    _verification_preset,
)

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.8"
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.7"
SOURCE_REVISION_ID = "itemrev_" + "4" * 32


def _variation_requirement() -> EducationalRetrievalRequirementV2:
    return EducationalRetrievalRequirementV2(
        corpus_key="integrated-science-textbooks",
        required_item_elements=("choice", "paragraph"),
        past_exam_variation=PastExamVariationRequest(
            source_item_revision_id=SOURCE_REVISION_ID,
            variation_axes=("CONTEXT", "DISTRACTORS", "REASONING_PATH", "VALUES"),
        ),
    )


def _variation_start() -> dict[str, object]:
    guidance = "고정한 기출의 핵심 개념과 평가 목표를 유지하면서 새 문항으로 변형한다."
    return {
        "definition_key": "generic-item-development",
        "definition_version": "1.14.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "skip",
        "pack_key": "generated-knowledge-item",
        "environment": "development",
        "source_intake_batch_ids": [],
        "registry_mode": "CREATE_ITEM",
        "item_id": None,
        "base_revision_id": None,
        "stimulus_asset_key": None,
        "execution_preset_key": "knowledge-grounded-item",
        "production_occurrence": None,
        "expected_resolution": None,
        "item_brief": {
            "schema_version": "4.0",
            "subject": "통합과학",
            "topic": "시간과 공간",
            "task_type": "자료 해석",
            "difficulty": "중",
            "authoring_guidance": guidance,
            "authoring_guidance_sha256": "sha256:"
            + hashlib.sha256(guidance.encode("utf-8")).hexdigest(),
            "curriculum_selected_unit_key": "eom.is.middle.1-1",
            "mock_exam_slot": None,
            "material_requirement": {
                "schema_version": "content-team-material-requirement/1.0",
                "form": "TABLE",
                "panel_count": 1,
            },
            "original_request_sha256": hashlib.sha256(guidance.encode()).hexdigest(),
        },
        "educational_retrieval": _variation_requirement().model_dump(mode="json"),
    }


def _variation_preset() -> ExecutionPresetRevisionV2:
    value = _verification_preset().model_dump(mode="json")
    value["retrieval_policy"]["allowed_corpus_keys"] = ["integrated-science-textbooks"]
    value["retrieval_policy"]["allowed_source_classes"] = ["PAST_EXAM"]
    value["content_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "content_sha256"}
    )
    return ExecutionPresetRevisionV2.model_validate(value)


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_variation_contracts_are_schema_first_mirrored_and_semantically_closed() -> None:
    for canonical, packaged in (
        (
            ROOT / "schemas/knowledge/past-exam-variation-request-v1.schema.json",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
            "past-exam-variation-request-v1.schema.json",
        ),
        (
            ROOT / "schemas/knowledge/educational-retrieval-requirement-v2.schema.json",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
            "educational-retrieval-requirement-v2.schema.json",
        ),
    ):
        assert canonical.read_bytes() == packaged.read_bytes()
    request = _variation_requirement()
    validate_contract(
        "past-exam-variation-request", request.past_exam_variation.model_dump(mode="json")
    )
    validate_contract("educational-retrieval-requirement-v2", request.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="sorted and unique"):
        PastExamVariationRequest(
            source_item_revision_id=SOURCE_REVISION_ID,
            variation_axes=("VALUES", "CONTEXT"),
        )
    with pytest.raises(ValidationError):
        EducationalRetrievalRequirementV2.model_validate(
            request.model_dump(mode="json") | {"source_classes": ["TEXTBOOK"]}
        )


def test_workflow_start_v4_accepts_only_exact_create_item_variation_pairing() -> None:
    request = _variation_start()
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.definition_version == "1.14.0"
    assert isinstance(parsed.educational_retrieval, EducationalRetrievalRequirementV2)
    internal = _workflow_request_from_api(parsed)
    assert isinstance(internal.educational_retrieval, EducationalRetrievalRequirementV2)
    assert internal.educational_retrieval.curriculum_root_key is None
    assert internal.educational_retrieval.past_exam_variation.source_item_revision_id == (
        SOURCE_REVISION_ID
    )
    assert internal.item_brief is not None
    assert internal.item_brief.curriculum_scope is not None
    assert internal.item_brief.curriculum_scope.selected_unit_key == "eom.is.middle.1-1"

    with pytest.raises(ValidationError, match=r"workflow 1\.14"):
        WorkflowStartRequest.model_validate(request | {"definition_version": "1.13.0"})
    with pytest.raises(ValidationError, match="CREATE_ITEM"):
        WorkflowStartRequest.model_validate(
            request
            | {
                "registry_mode": "REVISE_ITEM",
                "item_id": "item_" + "a" * 32,
                "base_revision_id": "itemrev_" + "b" * 32,
            }
        )


def test_variation_workflow_and_pack_form_one_immutable_successor_family() -> None:
    workflow = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.14.yaml",
        {"authoring", "image", "review", "item_management"},
    ).definition
    pack = compile_pack(PACK)
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )

    assert workflow.definition_version == "1.14.0"
    assert workflow.limits.max_rework_cycles == 3
    assert (
        WORKFLOW_ADMISSION_BY_IDENTITY[("generic-item-development", "1.14.0")].role_protocol_version
        == "workflow-role/1.24.0"
    )
    assert pack.manifest.pack.version == "1.20.8"
    assert pack.manifest.compatibility.workflow_definitions[0].versions == ("1.14.0",)
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.8", request
    )

    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
    }
    authoring = (PACK / "prompt-templates/authoring.md").read_text(encoding="utf-8")
    review = (PACK / "prompt-templates/review.md").read_text(encoding="utf-8")
    for required in (
        "references/variation/request.json",
        "references/variation/source-item.json",
        "NO_STEM_CHOICE_ANSWER_COPY",
        "item_revision_id",
        "STRUCTURE_PATTERN",
    ):
        assert required in authoring
    for required in (
        "references/variation/request.json",
        "references/variation/source-item.json",
        "VARIATION_REQUIREMENT_MISMATCH",
        "ORIGINALITY_RISK",
    ):
        assert required in review


def test_request_draft_emits_exact_source_v2_intent_without_changing_normal_generation() -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    draft = normalize_request(
        RequestDraftInput(
            original_request_text="시간과 공간 단원의 고정 기출을 바탕으로 새 문항을 출제해줘."
        ),
        now=now,
        token="a" * 32,
    )
    plain = workflow_start_payload(draft)
    assert plain["definition_version"] == "1.16.0"
    assert "educational_retrieval" not in plain

    update = RequestDraftUpdate.model_validate(
        {
            **{
                name: getattr(draft, name)
                for name in RequestDraftUpdate.model_fields
                if name
                not in {
                    "knowledge_grounding",
                    "curriculum_selected_unit_key",
                    "past_exam_variation",
                }
            },
            "knowledge_grounding": True,
            "curriculum_selected_unit_key": "eom.is.middle.1-1",
            "past_exam_variation": {
                "source_item_revision_id": SOURCE_REVISION_ID,
                "variation_axes": ["CONTEXT", "DISTRACTORS", "REASONING_PATH", "VALUES"],
            },
        }
    )
    varied = update_draft(draft, update, now=now)
    payload = workflow_start_payload(varied, graph_corpus_key="integrated-science-textbooks")
    assert payload["definition_version"] == "1.16.0"
    assert payload["registry_mode"] == "CREATE_ITEM"
    assert payload["educational_retrieval"] == _variation_requirement().model_dump(mode="json")
    assert WorkflowStartRequest.model_validate(payload).definition_version == "1.16.0"

    studio = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    assert "state.curriculumOutline?.graph_grounding_available !== true" in studio
    assert "candidate.unit_key" in studio
    assert "entry.curriculum_units[0]" not in studio


def test_resolver_pins_exact_variation_intent_in_v16_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = _variation_preset()
    evidence = _evidence(manifest_schema_version="5.0")
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "c" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.14.0",
        workflow_definition_sha256="sha256:" + "d" * 64,
        workflow_role_schema_version="workflow-role/1.24.0",
        content_pack_release_id="packrel_" + "e" * 32,
        content_pack_sha256="sha256:" + "f" * 64,
        graph_snapshot_revision_id=evidence.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=evidence.evidence_bundle_revision_id,
    )
    captured: dict[str, Any] = {}

    def record(_session: object, *, document: dict[str, Any], dependencies: object) -> object:
        del dependencies
        captured.update(document)
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    plan = resolve_knowledge_backed_execution_plan(
        _Session(preset),  # type: ignore[arg-type]
        preset_revision_id=preset.preset_revision_id,
        requirement=_variation_requirement(),
        evidence=evidence,
        dependencies=dependencies,
        steps=(
            ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),
            ExecutionStepRequirement("review", WorkerRole.REVIEW),
        ),
        resolved_at=NOW,
    )

    assert isinstance(plan, ResolvedExecutionPlanV16)
    assert _parse_review_escalation_plan(plan.model_dump(mode="json")) == plan
    with pytest.raises(ValueError, match="plan family is unsupported"):
        _parse_review_escalation_plan({"schema_version": "resolved-execution-plan/15.0"})
    assert plan.retrieval_requirement.past_exam_variation.source_item_revision_id == (
        SOURCE_REVISION_ID
    )
    assert plan.plan_sha256 == content_sha256(
        {key: item for key, item in captured.items() if key != "plan_sha256"}
    )


def test_exact_source_structure_citation_is_a_mechanical_commit_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _past_exam_variation_fixture(tmp_path, monkeypatch)
    plan_record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    plan = ResolvedExecutionPlanV16.model_validate(plan_record.canonical_document)
    manifest = EvidenceBundleManifestV5.model_validate(fixture["manifest"])
    citation = EvidenceUsageCitationV1(
        evidence_id=manifest.entries[0].evidence_id,
        anchor_ids=manifest.entries[0].anchor_ids,
        application="STRUCTURE_PATTERN",
        application_description="The exact past-exam structure informed the new stem.",
        draft_json_paths=("/stem",),
    )

    _validate_variation_source_citation(plan, manifest, (citation,))

    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate_variation_source_citation(
            plan,
            manifest,
            (citation.model_copy(update={"application": "AVOID_COPY_CHECK"}),),
        )
    assert captured.value.code == "EVIDENCE_VARIATION_SOURCE_NOT_USED"
