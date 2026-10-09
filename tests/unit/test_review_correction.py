from __future__ import annotations

import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_hwpx_contracts import ContentTeamStatement
from eom_identifiers import content_sha256
from eom_workflow import (
    ReviewPolicyCorrection,
    ReviewPolicyCorrectionRequired,
    ReviewRoutingPolicyValues,
    WorkflowReviewCorrectionDirective,
    build_review_correction_directive,
    load_review_correction_directive_schema,
    validate_review_correction_against_source,
    validate_schema_message,
)
from eom_workflow.models import (
    ArtifactPointer,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV12,
)
from eom_workflow.review_escalation import (
    build_review_escalation_directive,
    structural_review_complexity,
    validate_escalated_review_against_source,
    validate_primary_review_escalation_policy,
)
from eom_workflow.schemas import WorkflowSchemaError, role_schema_bundle_hash
from pydantic import ValidationError

from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import (
    _authoring_result,
    _v12_plan_review_step,
    _v12_review_document,
)


def _pointer(
    result: ContentTeamAuthoringRoleResultV12 | ContentTeamReviewRoleResultV12,
    *,
    attempt: int = 1,
) -> ArtifactPointer:
    authoring = isinstance(result, ContentTeamAuthoringRoleResultV12)
    return ArtifactPointer(
        step_key="authoring" if authoring else "review",
        attempt=attempt,
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_sha256(result.model_dump(mode="json")),
        result_schema="authoring-result@12.0" if authoring else "review-result@12.0",
    )


@pytest.fixture
def sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12]:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.13.0",
    )
    document = _authoring_result(fixture).model_dump(mode="json")
    document["protocol_version"] = "workflow-role/1.24.0"
    return fixture, ContentTeamAuthoringRoleResultV12.model_validate(document)


def _primary_correction(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
    *,
    attempt: int = 1,
    pass_number: Literal[2, 3] = 2,
) -> tuple[WorkflowReviewCorrectionDirective, ContentTeamReviewRoleResultV12]:
    fixture, authoring = sources
    bad_review = ContentTeamReviewRoleResultV12.model_validate(
        _v12_review_document(fixture, score=structural_review_complexity(authoring) + 1)
    )
    with pytest.raises(ReviewPolicyCorrectionRequired) as captured:
        validate_primary_review_escalation_policy(authoring=authoring, review=bad_review)
    directive = build_review_correction_directive(
        workflow_id=authoring.workflow_id,
        reviewed_authoring=_pointer(authoring),
        source_review=_pointer(bad_review, attempt=attempt),
        review_pass="PRIMARY",
        pass_number=pass_number,
        issue=captured.value.issue,
    )
    return directive, bad_review


@pytest.mark.parametrize("attempt,pass_number", [(1, 2), (6, 2), (7, 3)])
def test_correction_schema_and_model_bind_exact_pins_and_separate_proof_count(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
    attempt: int,
    pass_number: Literal[2, 3],
) -> None:
    directive, source = _primary_correction(sources, attempt=attempt, pass_number=pass_number)
    document = directive.model_dump(mode="json")
    validate_schema_message(
        load_review_correction_directive_schema(), document, directive.schema_version
    )
    assert WorkflowReviewCorrectionDirective.model_validate(document) == directive
    assert directive.next_attempt == attempt + 1
    assert directive.pass_number == pass_number
    assert directive.issue.code == "REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH"
    assert directive.issue.expected.structural_complexity_score + 1 == (
        directive.issue.observed.structural_complexity_score
    )
    assert directive.decision_sha256 == content_sha256(
        {key: value for key, value in document.items() if key != "decision_sha256"}
    )
    validate_review_correction_against_source(
        directive=directive, authoring=sources[1], source=source, escalation_directive=None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("pass_number", 4),
        ("pass_number", 1),
        ("next_attempt", 11),
        ("review_pass", "REPAIR"),
        ("workflow_id", "workflow_other"),
        ("unrecognized", "value"),
    ],
)
def test_correction_rejects_unknown_fields_and_unbounded_proofs(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12], field: str, value: object
) -> None:
    directive, _ = _primary_correction(sources)
    document = directive.model_dump(mode="json")
    document[field] = value
    with pytest.raises(WorkflowSchemaError):
        validate_schema_message(
            load_review_correction_directive_schema(), document, directive.schema_version
        )
    with pytest.raises(ValidationError):
        WorkflowReviewCorrectionDirective.model_validate(document)


@pytest.mark.parametrize(
    "mutation",
    ["hash", "next_attempt", "source_attempt", "source_schema", "authoring_step", "same_identity"],
)
def test_correction_rejects_hash_attempt_and_pointer_tampering(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12], mutation: str
) -> None:
    directive, _ = _primary_correction(sources)
    document = directive.model_dump(mode="json")
    if mutation == "hash":
        document["issue"]["expected"]["structural_complexity_score"] += 1
    elif mutation in {"next_attempt", "source_attempt"}:
        document[mutation] += 1
    elif mutation == "source_schema":
        document["source_review"]["result_schema"] = "review-result@11.0"
    elif mutation == "authoring_step":
        document["reviewed_authoring"]["step_key"] = "review"
    else:
        document["source_review"]["logical_artifact_id"] = document["reviewed_authoring"][
            "logical_artifact_id"
        ]
    if mutation != "hash":
        document["decision_sha256"] = content_sha256(
            {key: value for key, value in document.items() if key != "decision_sha256"}
        )
    with pytest.raises(ValidationError):
        WorkflowReviewCorrectionDirective.model_validate(document)


def test_correction_rejects_self_hashed_forged_policy_expectation(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
) -> None:
    directive, source = _primary_correction(sources)
    document = directive.model_dump(mode="json")
    document["issue"]["expected"]["structural_complexity_score"] = 10
    document["decision_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "decision_sha256"}
    )
    forged = WorkflowReviewCorrectionDirective.model_validate(document)
    with pytest.raises(ValueError, match="independently computed policy"):
        validate_review_correction_against_source(
            directive=forged, authoring=sources[1], source=source, escalation_directive=None
        )


def test_correction_rejects_foreign_workflow_and_missing_defect(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
) -> None:
    directive, source = _primary_correction(sources)
    foreign = source.model_copy(update={"workflow_id": "workflow_" + "f" * 32})
    with pytest.raises(ValueError, match="source identities"):
        validate_review_correction_against_source(
            directive=directive, authoring=sources[1], source=foreign, escalation_directive=None
        )
    fixture, authoring = sources
    correct_review = ContentTeamReviewRoleResultV12.model_validate(
        _v12_review_document(fixture, score=structural_review_complexity(authoring))
    )
    with pytest.raises(ValueError, match="no correctable policy defect"):
        validate_review_correction_against_source(
            directive=directive,
            authoring=authoring,
            source=correct_review,
            escalation_directive=None,
        )


@pytest.mark.parametrize("reasons", [("VISUAL_RISK", "EVIDENCE_GAP"), ("EVIDENCE_GAP",) * 2])
def test_correction_reasons_are_ordered_unique(reasons: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="sorted and unique"):
        ReviewRoutingPolicyValues(
            structural_complexity_score=1,
            reason_codes=reasons,  # type: ignore[arg-type]
            decision="REQUIRED",
        )


def test_correction_code_must_name_a_real_difference() -> None:
    values = ReviewRoutingPolicyValues(
        structural_complexity_score=1, reason_codes=(), decision="NOT_REQUIRED"
    )
    with pytest.raises(ValidationError, match="differing value"):
        ReviewPolicyCorrection(
            code="REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH", expected=values, observed=values
        )


def test_primary_wrong_tier_is_fatal_not_correctable(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
) -> None:
    _, source = _primary_correction(sources)
    assessment = source.output.independent_review_report.escalation_assessment
    mutated = source.model_copy(
        update={
            "output": source.output.model_copy(
                update={
                    "independent_review_report": source.output.independent_review_report.model_copy(
                        update={
                            "escalation_assessment": assessment.model_copy(
                                update={"review_pass": "ESCALATED"}
                            )
                        }
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError) as captured:
        validate_primary_review_escalation_policy(authoring=sources[1], review=mutated)
    assert not isinstance(captured.value, ReviewPolicyCorrectionRequired)


def test_primary_foreign_workflow_is_fatal_even_with_a_correctable_score(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
) -> None:
    _, source = _primary_correction(sources)
    foreign = source.model_copy(update={"workflow_id": "workflow_" + "f" * 32})
    with pytest.raises(ValueError, match="workflow identity differs") as captured:
        validate_primary_review_escalation_policy(authoring=sources[1], review=foreign)
    assert not isinstance(captured.value, ReviewPolicyCorrectionRequired)


def test_three_statements_without_visuals_have_complexity_one(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
) -> None:
    fixture, original = sources
    statements = tuple(
        ContentTeamStatement.model_validate({"label": label, "text": f"진술 {label}"})
        for label in ("ㄱ", "ㄴ", "ㄷ")
    )
    draft = original.output.draft.model_copy(update={"statements": statements})
    authoring = original.model_copy(
        update={"output": original.output.model_copy(update={"draft": draft})}
    )
    assert not draft.visuals
    assert structural_review_complexity(authoring) == 1
    review = ContentTeamReviewRoleResultV12.model_validate(_v12_review_document(fixture, score=2))
    with pytest.raises(ReviewPolicyCorrectionRequired) as captured:
        validate_primary_review_escalation_policy(authoring=authoring, review=review)
    assert captured.value.issue.expected.structural_complexity_score == 1
    assert captured.value.issue.observed.structural_complexity_score == 2


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("reason_codes", ("EVIDENCE_GAP",), "REVIEW_ESCALATION_REASONS_MISMATCH"),
        ("decision", "REQUIRED", "REVIEW_ESCALATION_DECISION_MISMATCH"),
    ],
)
def test_only_closed_policy_values_raise_typed_correction(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
    field: str,
    value: object,
    code: str,
) -> None:
    fixture, authoring = sources
    source = ContentTeamReviewRoleResultV12.model_validate(
        _v12_review_document(fixture, score=structural_review_complexity(authoring))
    )
    report = source.output.independent_review_report
    assessment = report.escalation_assessment.model_copy(update={field: value})
    review = source.model_copy(
        update={
            "output": source.output.model_copy(
                update={
                    "independent_review_report": report.model_copy(
                        update={"escalation_assessment": assessment}
                    )
                }
            )
        }
    )
    with pytest.raises(ReviewPolicyCorrectionRequired) as captured:
        validate_primary_review_escalation_policy(authoring=authoring, review=review)
    assert captured.value.issue.code == code


def test_escalated_correctable_metadata_preserves_tier_and_trust_closure(
    sources: tuple[dict[str, Any], ContentTeamAuthoringRoleResultV12],
) -> None:
    fixture, authoring = sources
    score = structural_review_complexity(authoring)
    reasons = ("CANDIDATE_FINDING_PRESENT", "EVIDENCE_UNCERTAINTY")
    primary = ContentTeamReviewRoleResultV12.model_validate(
        _v12_review_document(
            fixture, score=score, candidate_disposition="UNCERTAIN", reasons=reasons
        )
    )
    escalation = build_review_escalation_directive(
        workflow_id=authoring.workflow_id,
        reviewed_authoring=_pointer(authoring),
        source_review=_pointer(primary),
        authoring_result=authoring,
        review_result=primary,
        plan_step=_v12_plan_review_step(),
    )
    assert escalation is not None
    document = _v12_review_document(
        fixture,
        score=score + 1,
        candidate_disposition="DEMOTED",
        reasons=reasons,
        review_pass="ESCALATED",
        source_review=_pointer(primary),
    )
    source = ContentTeamReviewRoleResultV12.model_validate(document)
    with pytest.raises(ReviewPolicyCorrectionRequired) as captured:
        validate_escalated_review_against_source(
            directive=escalation, source=primary, escalated=source
        )
    correction = build_review_correction_directive(
        workflow_id=authoring.workflow_id,
        reviewed_authoring=_pointer(authoring),
        source_review=_pointer(source, attempt=2),
        review_pass="ESCALATED",
        pass_number=2,
        issue=captured.value.issue,
    )
    assert correction.issue.expected.decision == "COMPLETED"
    validate_review_correction_against_source(
        directive=correction, authoring=authoring, source=source, escalation_directive=escalation
    )
    changed = deepcopy(document)
    changed["output"]["independent_review_report"]["candidate_findings"][0]["draft_json_paths"] = [
        "/stem"
    ]
    corrupted = ContentTeamReviewRoleResultV12.model_validate(changed)
    with pytest.raises(ValueError, match="candidate evidence differs") as fatal:
        validate_escalated_review_against_source(
            directive=escalation, source=primary, escalated=corrupted
        )
    assert not isinstance(fatal.value, ReviewPolicyCorrectionRequired)


def test_released_role_contract_hash_is_unchanged() -> None:
    assert role_schema_bundle_hash("workflow-role/1.24.0") == (
        "sha256:dcd6cd56fd04f49897feead527ee08305f86e651268fee7915527a0b4f623035"
    )


def test_correction_schema_canonical_source_and_materialized_package_are_identical() -> None:
    logical_name = "workflow-review-correction-directive-v1.schema.json"
    root = Path(__file__).resolve().parents[2]
    canonical = (root / "schemas/workflow" / logical_name).read_bytes()
    materialized = files("eom_workflow").joinpath("resources", logical_name).read_bytes()
    assert materialized == canonical
    assert load_review_correction_directive_schema() == json.loads(canonical)
