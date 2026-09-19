from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import content_sha256
from eom_workflow import (
    WORKFLOW_ADMISSION_BY_IDENTITY,
    ArtifactPointer,
    WorkflowReviewReworkDirective,
    build_review_rework_directive,
    compile_definition,
)
from eom_workflow.models import (
    ContentTeamReviewRoleResultV11,
    WorkflowRequest,
)
from eom_workflow.schemas import (
    load_review_rework_directive_schema,
    validate_schema_message,
)

from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import _authoring_result, _review_document

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content/packs/generated-knowledge-item/1.18.0"
WORKFLOW = ROOT / "config/workflows/generic-item-development.v1.12.yaml"


def _pointer(step_key: str, attempt: int, result_schema: str, marker: str) -> ArtifactPointer:
    return ArtifactPointer(
        step_key=step_key,
        attempt=attempt,
        job_id="job_" + marker * 32,
        logical_artifact_id="artifact_" + marker * 32,
        revision_id="rev_" + marker * 32,
        content_hash="sha256:" + marker * 64,
        result_schema=result_schema,
    )


def test_review_rework_directive_is_schema_valid_self_hashed_and_bounded() -> None:
    directive = build_review_rework_directive(
        prior_authoring=_pointer("authoring", 1, "authoring-result@11.0", "1"),
        source_review=_pointer("review", 1, "review-result@11.0", "2"),
        blocking_finding_codes=("DIFFICULTY_MISMATCH",),
        disregarded_finding_codes=(),
        observed_rework_cycle_count=0,
        max_rework_cycles=3,
    )

    assert directive.outcome == "REWORK_AUTHORING"
    validate_schema_message(
        load_review_rework_directive_schema(),
        directive.model_dump(mode="json"),
        "workflow-review-rework-directive/1.0",
    )
    exhausted = build_review_rework_directive(
        prior_authoring=_pointer("authoring", 4, "authoring-result@11.0", "3"),
        source_review=_pointer("review", 4, "review-result@11.0", "4"),
        blocking_finding_codes=("DIFFICULTY_MISMATCH",),
        disregarded_finding_codes=(),
        observed_rework_cycle_count=3,
        max_rework_cycles=3,
    )
    assert exhausted.outcome == "HUMAN_REVIEW_REQUIRED"
    with pytest.raises(ValueError, match="hash differs"):
        WorkflowReviewReworkDirective.model_validate(
            directive.model_dump(mode="json") | {"decision_sha256": "sha256:" + "f" * 64}
        )


def test_unknown_blocking_finding_never_enters_an_automatic_loop() -> None:
    directive = build_review_rework_directive(
        prior_authoring=_pointer("authoring", 1, "authoring-result@11.0", "1"),
        source_review=_pointer("review", 1, "review-result@11.0", "2"),
        blocking_finding_codes=("FUTURE_UNCLASSIFIED_BLOCKER",),
        disregarded_finding_codes=(),
        observed_rework_cycle_count=0,
        max_rework_cycles=3,
    )

    assert directive.outcome == "HUMAN_REVIEW_REQUIRED"
    assert directive.human_required_finding_codes == ("FUTURE_UNCLASSIFIED_BLOCKER",)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("prior_authoring.attempt", 11, "source attempt exceeds"),
        ("repairable_finding_codes", ["invalid-code"], "finding code is invalid"),
    ],
)
def test_review_rework_pydantic_semantics_match_schema_bounds(
    field: str,
    value: object,
    match: str,
) -> None:
    directive = build_review_rework_directive(
        prior_authoring=_pointer("authoring", 1, "authoring-result@11.0", "1"),
        source_review=_pointer("review", 1, "review-result@11.0", "2"),
        blocking_finding_codes=("DIFFICULTY_MISMATCH",),
        disregarded_finding_codes=(),
        observed_rework_cycle_count=0,
        max_rework_cycles=3,
    ).model_dump(mode="json")
    target: dict[str, object] = directive
    parts = field.split(".")
    for part in parts[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[parts[-1]] = value
    directive["decision_sha256"] = content_sha256(
        {key: item for key, item in directive.items() if key != "decision_sha256"}
    )

    with pytest.raises(ValueError, match=match):
        WorkflowReviewReworkDirective.model_validate(directive)


def test_catalog_disregards_proven_false_material_profile_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.12.0",
    )
    authoring_result = _authoring_result(fixture)
    authoring = _pointer("authoring", 1, "authoring-result@11.0", "1")
    review = _pointer("review", 1, "review-result@11.0", "2")
    review_document = _review_document(fixture)
    review_document["output"]["evidence_usage_attestation"]["authoring_artifact"] = {
        "logical_artifact_id": authoring.logical_artifact_id,
        "revision_id": authoring.revision_id,
        "content_hash": authoring.content_hash,
        "result_schema": authoring.result_schema,
    }
    review_document["output"]["review"]["findings"] = [
        {
            "code": "MATERIAL_PROFILE_MISMATCH",
            "severity": "blocking",
            "message": "The editorial task label and material form differ.",
        }
    ]
    review_result = ContentTeamReviewRoleResultV11.model_validate(review_document)
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )

    def load_result(
        _service: WorkflowCatalogService, _workflow: object, pointer: ArtifactPointer
    ) -> tuple[dict[str, object], object]:
        parsed = authoring_result if pointer.step_key == "authoring" else review_result
        return parsed.model_dump(mode="json"), parsed

    monkeypatch.setattr(WorkflowCatalogService, "_load_upstream_result", load_result)
    service = object.__new__(WorkflowCatalogService)
    directive = service.classify_review_rework(
        workflow=object(),  # type: ignore[arg-type]
        request=request,
        artifacts=(authoring, review),
        observed_rework_cycle_count=0,
        max_rework_cycles=3,
    )

    assert directive.outcome == "READY_FOR_HUMAN"
    assert directive.verified_blocking_finding_codes == ()
    assert directive.disregarded_finding_codes == ("MATERIAL_PROFILE_MISMATCH",)


def test_prompt_materialization_resolves_exact_prior_results_only_at_the_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.12.0",
    )
    authoring_result = _authoring_result(fixture)
    authoring = _pointer("authoring", 1, "authoring-result@11.0", "1")
    review = _pointer("review", 1, "review-result@11.0", "2")
    review_document = _review_document(fixture)
    review_document["output"]["evidence_usage_attestation"]["authoring_artifact"] = {
        "logical_artifact_id": authoring.logical_artifact_id,
        "revision_id": authoring.revision_id,
        "content_hash": authoring.content_hash,
        "result_schema": authoring.result_schema,
    }
    review_result = ContentTeamReviewRoleResultV11.model_validate(review_document)
    directive = build_review_rework_directive(
        prior_authoring=authoring,
        source_review=review,
        blocking_finding_codes=("DIFFICULTY_MISMATCH",),
        disregarded_finding_codes=(),
        observed_rework_cycle_count=0,
        max_rework_cycles=3,
    )

    def load_result(
        _service: WorkflowCatalogService, _workflow: object, pointer: ArtifactPointer
    ) -> tuple[dict[str, object], object]:
        parsed = authoring_result if pointer.step_key == "authoring" else review_result
        return parsed.model_dump(mode="json"), parsed

    monkeypatch.setattr(WorkflowCatalogService, "_load_upstream_result", load_result)
    service = object.__new__(WorkflowCatalogService)
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    context = service._prompt_context(
        SimpleNamespace(
            workflow_id="workflow_" + "9" * 32,
            runtime_context={
                "review_rework_history": [directive.model_dump(mode="json")],
            },
        ),  # type: ignore[arg-type]
        SimpleNamespace(step_key="authoring"),  # type: ignore[arg-type]
        request,
        (),
        "packrel_" + "8" * 32,
    )

    assert json.loads(context["rework"]["feedback_json"]) == directive.model_dump(mode="json")
    assert json.loads(context["rework"]["prior_authoring_result_json"])["artifact"] == (
        authoring_result.artifact.model_dump(mode="json")
    )
    assert json.loads(context["rework"]["source_review_result_json"])["artifact"] == (
        review_result.artifact.model_dump(mode="json")
    )


def test_bounded_rework_pack_workflow_and_prompts_form_one_successor_family() -> None:
    pack = compile_pack(PACK)
    definition = compile_definition(
        WORKFLOW,
        {"authoring", "image", "review", "item_management"},
    ).definition

    assert pack.manifest.pack.version == "1.18.0"
    assert pack.source_tree_sha256 == (
        "sha256:88ed207b452fefd4c867e78dceded062e26b21e3b796f7c3b16eddc5b74de299"
    )
    assert definition.definition_version == "1.12.0"
    assert definition.limits.max_rework_cycles == 3
    assert definition.limits.max_step_attempts == 10
    assert definition.automatic_review_rework is not None
    assert definition.automatic_review_rework.source_review_step == "review"
    assert definition.automatic_review_rework.target_authoring_step == "authoring"
    assert (
        WORKFLOW_ADMISSION_BY_IDENTITY[("generic-item-development", "1.12.0")].role_protocol_version
        == "workflow-role/1.23.0"
    )
    for role in ("authoring", "review"):
        prompt = (PACK / "prompt-templates" / f"{role}.md").read_text(encoding="utf-8")
        assert "REWORK_FEEDBACK_JSON" in prompt
        assert "PRIOR_AUTHORING_RESULT_JSON" in prompt
        assert "SOURCE_REVIEW_RESULT_JSON" in prompt
        assert "mock_exam_slot" in prompt
    assert "오케스트레이터" in (PACK / "prompt-templates/authoring.md").read_text(encoding="utf-8")
