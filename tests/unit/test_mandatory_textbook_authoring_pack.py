"""Exact Pack successor and trusted textbook-use checks; no live worker or DB."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.evidence_usage_validation import (
    EvidenceUsageValidationError,
    _validate_authoring_result,
    _validate_authoring_textbook_use,
    _validate_independent_review_report,
    _validate_review_result_v12,
    _validate_review_textbook_use,
)
from eom_workflow import (
    EvidenceResultArtifactPointerV3,
    ResolvedExecutionPlanV19,
    ReviewEvidenceUsageValidationReceiptV3,
)
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV12,
    RoleWorkerInput,
    WorkerRequest,
)

from tests.unit.test_content_team_v3_protocol import _content_v3
from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import (
    EVIDENCE_ID,
    _authoring_result,
    _materials,
    _persist_authoring,
    _upgrade_fixture_plan_to_v12,
    _v12_review_document,
)
from tests.unit.test_item_authoring_textbook_selection import _textbook

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.18"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.19"
TEXTBOOK_ID = "evidenceitem_" + "4" * 32


def test_successor_preserves_predecessor_image_and_team_guidance(tmp_path: Path) -> None:
    before = {
        path.relative_to(SOURCE): path.read_bytes() for path in SOURCE.rglob("*") if path.is_file()
    }
    after = {
        path.relative_to(TARGET): path.read_bytes() for path in TARGET.rglob("*") if path.is_file()
    }
    assert before.keys() == after.keys()
    assert {path for path in before if before[path] != after[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
        Path("metadata-schemas/item-metadata.schema.json"),
    }
    assert (
        compile_pack(SOURCE).manifest.compatibility == compile_pack(TARGET).manifest.compatibility
    )
    assert (
        build_pack(SOURCE, tmp_path / "old").bundle_sha256
        == SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.18"]
    )
    assert (
        build_pack(TARGET, tmp_path / "new").bundle_sha256
        == SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.19"]
    )


@pytest.mark.parametrize("role", ("authoring", "review"))
def test_successor_prompts_require_actual_textbook_without_changing_output_schema(
    role: str,
) -> None:
    text = (TARGET / f"prompt-templates/{role}.md").read_text()
    assert "일반 지식" in text and "역할 실행을 명시적으로 실패" in text
    assert "TEXTBOOK" in text and "GROUNDING" in text
    assert "general_model_knowledge" not in text
    assert "BEGIN_SYSTEM_RAG_SIMILARITY_REFERENCE_V2" in text
    assert "구형 `anchor_profile` 필드는 이 형식에 없다" in text
    profile = next(
        profile for profile in compile_pack(TARGET).profiles if profile.profile.type == role
    )
    assert profile.output_schema_ref == f"{role}-result@12.0"
    if role == "review":
        assert "curriculum_assessment" in text and "SCIENTIFIC_VALIDATION" in text


def _case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, version: str = "1.20.19"
) -> dict[str, Any]:
    fixture = _knowledge_fixture(tmp_path, monkeypatch, manifest_schema_version="5.0")
    _upgrade_fixture_plan_to_v12(fixture)
    manifest = fixture["manifest"]
    textbook = _textbook()
    manifest["entries"].append(
        {
            "evidence_id": TEXTBOOK_ID,
            "evidence_kind": "DOCUMENT",
            "use": "GROUNDING",
            "source": textbook.source.model_dump(mode="json"),
            "graph_node_ids": list(textbook.node_ids),
            "anchor_ids": list(textbook.anchor_ids),
            "relevance_milli": textbook.relevance_milli,
            "answer_bearing": False,
            "solution_evidence": None,
        }
    )
    manifest["budget"]["document_count"] = 1
    manifest["budget"]["graph_node_count"] += 1
    fixture["context_payload"] += (
        f"- `{TEXTBOOK_ID}` score=850 use=GROUNDING class=TEXTBOOK source=`sourcefile_"
        + "8" * 32
        + "` nodes=knode_book: textbook concept\n"
    ).encode()
    manifest["materials"]["context_markdown"]["sha256"] = sha256_bytes(fixture["context_payload"])
    manifest["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    fixture["manifest_payload"] = canonical_json_bytes(manifest)
    record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    document = deepcopy(record.canonical_document)
    document.update(
        schema_version="resolved-execution-plan/19.0",
        workflow_definition_version="1.16.0",
        resolver_version="19.0.0",
        content_pack_sha256=SVG_LABEL_LAYOUT_PACK_BUNDLES[version],
        evidence_manifest_sha256=manifest["manifest_sha256"],
    )
    document["evidence_context_artifact"]["sha256"] = manifest["materials"]["context_markdown"][
        "sha256"
    ]
    document["plan_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    )
    fixture["plan"] = ResolvedExecutionPlanV19.model_validate(document)
    return fixture


def _grounded_authoring(fixture: dict[str, Any]) -> ContentTeamAuthoringRoleResultV12:
    document = _authoring_result(fixture).model_dump(mode="json")
    document["protocol_version"] = "workflow-role/1.24.0"
    document["output"]["evidence_usage"]["citations"].append(
        {
            "evidence_id": TEXTBOOK_ID,
            "anchor_ids": ["anchor_book"],
            "application": "CONCEPT_GROUNDING",
            "application_description": "The textbook concept supports the stem condition.",
            "draft_json_paths": ["/stem"],
        }
    )
    return ContentTeamAuthoringRoleResultV12.model_validate(document)


def _grounded_review(fixture: dict[str, Any]) -> dict[str, Any]:
    document = _v12_review_document(fixture)
    report = document["output"]["independent_review_report"]
    report["evidence_references"].append(
        {
            "evidence_id": TEXTBOOK_ID,
            "anchor_ids": ["anchor_book"],
            "purposes": ["CURRICULUM_SCOPE", "SCIENTIFIC_VALIDATION"],
        }
    )
    report["answer_review"]["claims"][0]["evidence_ids"] = [TEXTBOOK_ID]
    report["curriculum_assessment"]["evidence_ids"] = [TEXTBOOK_ID]
    for target in report["verification_targets"]:
        if target["target_kind"] in {"SCIENTIFIC_CLAIM", "CURRICULUM_SCOPE"}:
            target["required_source_classes"] = ["TEXTBOOK"]
            target["selected_evidence_ids"] = [TEXTBOOK_ID]
    return document


def test_successor_authoring_requires_used_textbook_not_only_selected_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _case(tmp_path, monkeypatch)
    old = _authoring_result(fixture)
    with pytest.raises(EvidenceUsageValidationError) as caught:
        _validate_authoring_result(fixture["plan"], _materials(fixture), old)
    assert caught.value.code == "EVIDENCE_TEXTBOOK_GROUNDING_UNUSED"
    assert _validate_authoring_result(
        fixture["plan"], _materials(fixture), _grounded_authoring(fixture)
    ).startswith("sha256:")


@pytest.mark.parametrize("version", ("1.20.18", "1.20.19"))
def test_exact_predecessor_pin_does_not_gain_new_textbook_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    fixture = _case(tmp_path, monkeypatch, version=version)
    authoring = _authoring_result(fixture)
    assert authoring.output.evidence_usage is not None
    if version == "1.20.18":
        _validate_authoring_textbook_use(
            fixture["plan"], _materials(fixture).manifest, authoring.output.evidence_usage.citations
        )
        _validate_review_textbook_use(
            fixture["plan"],
            _materials(fixture),
            ContentTeamReviewRoleResultV12.model_validate(_v12_review_document(fixture)),
        )
    else:
        with pytest.raises(EvidenceUsageValidationError):
            _validate_authoring_textbook_use(
                fixture["plan"],
                _materials(fixture).manifest,
                authoring.output.evidence_usage.citations,
            )


def test_textbook_review_binds_real_science_curriculum_and_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _case(tmp_path, monkeypatch)
    result = ContentTeamReviewRoleResultV12.model_validate(_grounded_review(fixture))
    _validate_independent_review_report(
        _materials(fixture), result, _content_v3().model_dump(mode="json")
    )
    _validate_review_textbook_use(fixture["plan"], _materials(fixture), result)


@pytest.mark.parametrize("fault", ("science", "curriculum", "science_target", "curriculum_target"))
def test_textbook_reference_cannot_replace_actual_judgment_and_target_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _case(tmp_path, monkeypatch)
    document = _grounded_review(fixture)
    report = document["output"]["independent_review_report"]
    if fault == "science":
        report["answer_review"]["claims"][0]["evidence_ids"] = [EVIDENCE_ID]
    elif fault == "curriculum":
        report["curriculum_assessment"]["evidence_ids"] = [EVIDENCE_ID]
    else:
        kind = "SCIENTIFIC_CLAIM" if fault == "science_target" else "CURRICULUM_SCOPE"
        for target in report["verification_targets"]:
            if target["target_kind"] == kind:
                target.update(
                    required_source_classes=[],
                    selected_evidence_ids=[],
                    evidence_status="NOT_APPLICABLE",
                )
    result = ContentTeamReviewRoleResultV12.model_validate(document)
    with pytest.raises(EvidenceUsageValidationError) as caught:
        _validate_review_textbook_use(fixture["plan"], _materials(fixture), result)
    assert caught.value.code == (
        "EVIDENCE_REVIEW_TEXTBOOK_TARGET_UNUSED"
        if fault.endswith("_target")
        else "EVIDENCE_REVIEW_TEXTBOOK_UNUSED"
    )


@pytest.mark.parametrize("omit_curriculum", (False, True))
def test_review_commit_boundary_applies_textbook_policy_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, omit_curriculum: bool
) -> None:
    fixture = _case(tmp_path, monkeypatch)
    authoring = _grounded_authoring(fixture)
    pointer = _persist_authoring(fixture, authoring)
    document = _grounded_review(fixture)
    attestation = document["output"]["evidence_usage_attestation"]
    attestation["authoring_artifact"] = {
        "logical_artifact_id": pointer.logical_artifact_id,
        "revision_id": pointer.revision_id,
        "content_hash": pointer.content_hash,
        "result_schema": pointer.result_schema,
    }
    assert authoring.output.evidence_usage is not None
    attestation["citations"] = [
        citation.model_dump(mode="json") for citation in authoring.output.evidence_usage.citations
    ]
    if omit_curriculum:
        document["output"]["independent_review_report"]["curriculum_assessment"]["evidence_ids"] = [
            EVIDENCE_ID
        ]
    result = ContentTeamReviewRoleResultV12.model_validate(document)
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.24.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="review",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(pointer,),
        artifact=result.artifact,
    )
    result_pointer = EvidenceResultArtifactPointerV3(
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        result_schema="review-result@12.0",
    )

    def validate() -> ReviewEvidenceUsageValidationReceiptV3:
        return _validate_review_result_v12(
            fixture["session"],
            plan=fixture["plan"],
            materials=_materials(fixture),
            worker_input=worker_input,
            result=result,
            result_artifact=result_pointer,
            canonical_artifact_root=fixture["artifact_root"],
            material_requirement=None,
        )

    if omit_curriculum:
        with pytest.raises(EvidenceUsageValidationError) as caught:
            validate()
        assert caught.value.code == "EVIDENCE_REVIEW_TEXTBOOK_UNUSED"
    else:
        receipt = validate()
        assert receipt.result_artifact == result_pointer
        assert receipt.authoring_artifact.content_hash == pointer.content_hash
