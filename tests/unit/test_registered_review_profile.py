"""Offline registered-review projection, never a model, storage or IAM admission."""

from __future__ import annotations

import ast
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import (
    REGISTERED_REVIEW_PROFILE_SCHEMA,
    REVIEW_PIXEL_LIMITATION,
    REVIEW_REASONING_LIMITATION,
    RegisteredReviewClaim,
    RegisteredReviewProfile,
    RegisteredReviewProfilePointer,
    RegisteredReviewSourceBasis,
    build_registered_review_profile,
    registered_review_profile_bytes,
    registered_review_profile_text,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_catalog_service.registered_review_projection import project_registered_review_solution
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_fixtures import NOW, profile
from tests.unit.registered_review_fixtures import (
    RegisteredReviewCase,
    registered_review_case,
    registered_review_profile,
)

ROOT = Path(__file__).resolve().parents[2]
INVALID = (ValueError, TypeError, SchemaError)


def _project(case: RegisteredReviewCase) -> RegisteredReviewProfile:
    return project_registered_review_solution(
        source_basis=case.basis,
        authoring=case.authoring,
        review=case.review,
        created_at=NOW,
    )


def _review(case: RegisteredReviewCase, body: dict) -> RegisteredReviewCase:
    review = type(case.review).model_validate(body)
    evidence = case.basis.review_evidence.model_dump(mode="json")
    evidence["review"]["artifact"]["sha256"] = sha256_bytes(
        canonical_json_bytes(review.model_dump(mode="json"))
    )
    evidence["evidence_sha256"] = content_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    checked = RegisteredItemReviewSolutionEvidence.model_validate(evidence)
    return replace(
        case,
        basis=RegisteredReviewSourceBasis(
            source=checked.source,
            graph_snapshot=case.basis.graph_snapshot,
            review_evidence=checked,
        ),
        review=review,
    )


def _leaf(value: object, pointer: str) -> object:
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def test_schema_precedes_model_and_packaged_bytes_are_hash_pinned():
    resource = CATALOG_SCHEMA_RESOURCES[REGISTERED_REVIEW_PROFILE_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(REGISTERED_REVIEW_PROFILE_SCHEMA))


@pytest.mark.parametrize("version", ("11.0", "12.0"))
def test_original_conclusions_pointers_and_identity_are_lossless_and_deterministic(version):
    case = registered_review_case(version)
    before = canonical_json_bytes(
        [
            case.basis.model_dump(mode="json"),
            case.authoring.model_dump(mode="json"),
            case.review.model_dump(mode="json"),
        ]
    )
    result = _project(case)
    assert result == _project(case)
    validate_contract(REGISTERED_REVIEW_PROFILE_SCHEMA, result.model_dump(mode="json"))
    assert (
        RegisteredReviewProfile.model_validate_json(registered_review_profile_bytes(result))
        == result
    )
    pointer = RegisteredReviewProfilePointer.from_profile(result)
    assert pointer.profile_revision_id == result.profile_revision_id
    assert pointer.schema_ref.endswith("/2.0")
    assert result.source_basis == case.basis
    report = case.review.output.independent_review_report
    summary = next(claim for claim in result.claims if claim.kind == "ANSWER_SUMMARY")
    assert summary.text == report.answer_review.verification_summary
    assert summary.subject == report.answer_review.derived_answer_number
    assert summary.verdict == report.answer_review.alignment
    for claim in result.claims:
        for path in claim.review_json_pointers:
            assert not isinstance(_leaf(case.review.model_dump(mode="json"), path), dict | list)
        for path in claim.draft_json_paths:
            assert not isinstance(
                _leaf(case.authoring.output.draft.model_dump(mode="json"), path), dict | list
            )
        assert all(
            key not in claim.model_dump()
            for key in ("facet", "node_ids", "anchor_ids", "reasoning_step_ids")
        )
    assert {REVIEW_REASONING_LIMITATION, REVIEW_PIXEL_LIMITATION} <= set(result.limitations)
    assert before == canonical_json_bytes(
        [
            case.basis.model_dump(mode="json"),
            case.authoring.model_dump(mode="json"),
            case.review.model_dump(mode="json"),
        ]
    )


def test_exact_maximum_length_conclusions_preserve_terminal_scientific_negation():
    case = registered_review_case()
    body = case.review.model_dump(mode="json")
    report = body["output"]["independent_review_report"]
    summary = "가" * 3992 + "보존되지않는다."
    conclusion = "나" * 1992 + "보존되지않는다."
    assert len(summary) == 4000 and len(conclusion) == 2000
    report["answer_review"]["verification_summary"] = summary
    report["answer_review"]["claims"][0]["conclusion"] = conclusion
    report["choice_diagnostics"][0]["rationale"] = conclusion
    result = _project(_review(case, body))
    assert summary in registered_review_profile_text(result)
    assert conclusion in registered_review_profile_text(result)
    assert any(claim.text == summary for claim in result.claims)
    assert any(claim.text == conclusion for claim in result.claims)


def test_internal_claim_key_changes_audit_identity_but_not_numerical_features():
    case = registered_review_case()
    body = case.review.model_dump(mode="json")
    body["output"]["independent_review_report"]["answer_review"]["claims"][0]["claim_key"] = (
        "claim_zchanged"
    )
    original, changed = _project(case), _project(_review(case, body))
    assert original.profile_id == changed.profile_id
    assert original.profile_revision_id != changed.profile_revision_id
    assert registered_review_profile_text(original) == registered_review_profile_text(changed)
    assert "claim_answer" not in registered_review_profile_text(original)
    assert "reviewclaim_" not in registered_review_profile_text(original)


@pytest.mark.parametrize("version", ("11.0", "12.0"))
def test_forged_frozen_conclusion_is_revalidated_before_projection(version):
    case = registered_review_case(version)
    original = case.review.output.independent_review_report
    claim = original.answer_review.claims[0].model_copy(update={"conclusion": "x" * 2001})
    forged = case.review.model_copy(
        update={
            "output": case.review.output.model_copy(
                update={
                    "independent_review_report": original.model_copy(
                        update={
                            "answer_review": original.answer_review.model_copy(
                                update={"claims": (claim,)}
                            )
                        }
                    )
                }
            )
        }
    )
    with pytest.raises(INVALID):
        _project(replace(case, review=forged))


@pytest.mark.parametrize("role", ("authoring", "review"))
@pytest.mark.parametrize("nested", (False, True))
def test_undeclared_frozen_extras_are_not_erased_by_role_serialization(role, nested):
    case = registered_review_case()
    result = getattr(case, role)
    forged = (
        result.model_copy(update={"output": result.output.model_copy(update={"unknown": True})})
        if nested
        else result.model_copy(update={"unknown": True})
    )
    with pytest.raises(ValueError, match="undeclared"):
        _project(replace(case, **{role: forged}))


def test_missing_grounded_declarations_cannot_claim_two_trusted_receipts():
    case = registered_review_case()
    body = case.review.model_dump(mode="json")
    report = body["output"]["independent_review_report"]
    report["evidence_references"] = []
    for claim in report["answer_review"]["claims"]:
        claim["evidence_ids"] = []
    for choice in report["choice_diagnostics"]:
        choice["evidence_ids"] = []
    for field in (
        "explanation_assessment",
        "curriculum_assessment",
        "originality_assessment",
        "visual_assessment",
    ):
        report[field]["evidence_ids"] = []
    body["output"]["evidence_usage_attestation"] = None
    review = type(case.review).model_validate(body)
    with pytest.raises(ValueError, match="grounded evidence"):
        _project(replace(case, review=review))


def test_all_25_original_conclusions_and_three_statements_are_preserved():
    case = registered_review_case()
    authored = case.authoring.model_dump(mode="json")
    draft = authored["output"]["draft"]
    draft["statements"] = [
        {"label": label, "text": f"{label}의 구체적 조건은 보존되지 않는다."}
        for label in ("ㄱ", "ㄴ", "ㄷ")
    ]
    for choice, text in zip(
        draft["choices"], ("ㄱ", "ㄱ, ㄷ", "ㄴ", "ㄴ, ㄷ", "ㄱ, ㄴ, ㄷ"), strict=True
    ):
        choice["text"] = text
    draft["answer"].update(
        answer_kind="STATEMENT_COMBINATION",
        statement_labels=["ㄱ", "ㄷ"],
        answer_content="ㄱ, ㄷ",
        raw_line="정답 : ② (ㄱ, ㄷ)",
    )
    draft["explanations"].update(
        correct_answer="ㄱ. 주어진 조건을 보존한다.\nㄷ. 결과를 보존한다.",
        wrong_answer="ㄴ. 조건이 성립하지 않는다.",
    )
    authoring = type(case.authoring).model_validate(authored)
    evidence = case.basis.review_evidence.model_dump(mode="json")
    evidence["authoring"]["artifact"]["sha256"] = sha256_bytes(
        canonical_json_bytes(authoring.model_dump(mode="json"))
    )
    evidence["evidence_sha256"] = content_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    checked = RegisteredItemReviewSolutionEvidence.model_validate(evidence)
    case = replace(
        case,
        authoring=authoring,
        basis=RegisteredReviewSourceBasis(
            source=checked.source, graph_snapshot=case.basis.graph_snapshot, review_evidence=checked
        ),
    )
    body = case.review.model_dump(mode="json")
    body["output"]["evidence_usage_attestation"]["authoring_artifact"]["content_hash"] = (
        checked.authoring.artifact.sha256
    )
    report = body["output"]["independent_review_report"]
    original_claim = report["answer_review"]["claims"][0]
    report["answer_review"]["claims"] = [
        original_claim
        | {"claim_key": f"claim_{index:02d}", "conclusion": f"조건 {index}은 보존되지 않는다."}
        for index in range(16)
    ]
    report["statement_diagnostics"] = [
        {
            "label": label,
            "verdict": "FALSE" if label == "ㄴ" else "TRUE",
            "rationale": f"{label}의 독립 판정은 조건의 부호를 보존한다.",
            "draft_json_paths": [f"/statements/{index}/text"],
            "evidence_ids": original_claim["evidence_ids"],
        }
        for index, label in enumerate(("ㄱ", "ㄴ", "ㄷ"))
    ]
    result = _project(_review(case, body))
    assert len(result.claims) == 25
    statements = tuple(claim for claim in result.claims if claim.kind == "STATEMENT_DIAGNOSTIC")
    assert {claim.subject for claim in statements} == {"ㄱ", "ㄴ", "ㄷ"}
    assert {claim.verdict for claim in statements} == {"TRUE", "FALSE"}
    assert all(claim.text in registered_review_profile_text(result) for claim in result.claims)


@pytest.mark.parametrize("field", ("workflow_id", "step_run_id", "job_id"))
@pytest.mark.parametrize("role", ("authoring", "review"))
def test_foreign_result_envelopes_do_not_reuse_registered_evidence(field, role):
    case = registered_review_case()
    result = getattr(case, role)
    prefix = {"workflow_id": "workflow_", "step_run_id": "steprun_", "job_id": "job_"}[field]
    forged = result.model_copy(update={field: prefix + "f" * 32})
    with pytest.raises(INVALID, match="envelope"):
        _project(replace(case, **{role: forged}))


@pytest.mark.parametrize("role", ("authoring", "review"))
@pytest.mark.parametrize("field", ("logical_artifact_id", "revision_id"))
def test_foreign_artifact_envelopes_fail(role, field):
    case = registered_review_case()
    result = getattr(case, role)
    prefix = "artifact_" if field == "logical_artifact_id" else "rev_"
    forged = result.model_copy(
        update={"artifact": result.artifact.model_copy(update={field: prefix + "f" * 32})}
    )
    with pytest.raises(INVALID, match="envelope"):
        _project(replace(case, **{role: forged}))


def test_mixed_released_role_families_are_not_silently_converted():
    old, new = registered_review_case(), registered_review_case("12.0")
    with pytest.raises(ValueError, match="families"):
        _project(replace(old, review=new.review))


@pytest.mark.parametrize(
    "path", ("/choices/00/text", "/choices/5/text", "/choices", "/missing", "/stem/text")
)
def test_existing_public_draft_scalar_validator_rejects_invalid_paths(path):
    case = registered_review_case()
    body = case.review.model_dump(mode="json")
    body["output"]["independent_review_report"]["answer_review"]["claims"][0][
        "draft_json_paths"
    ] = [path]
    with pytest.raises(ValueError):
        _project(_review(case, body))


def test_original_authoring_answer_and_review_must_match():
    case = registered_review_case()
    body = case.authoring.model_dump(mode="json")
    body["output"]["draft"]["answer"].update(
        number="①", answer_content="첫 번째 설명", raw_line="정답 : ① (첫 번째 설명)"
    )
    authoring = type(case.authoring).model_validate(body)
    with pytest.raises(ValueError, match="authored answer"):
        _project(replace(case, authoring=authoring))


@pytest.mark.parametrize(
    "field", ("logical_artifact_id", "revision_id", "content_hash", "result_schema")
)
def test_review_attestation_must_bind_the_same_original_authoring(field):
    case = registered_review_case()
    body = case.review.model_dump(mode="json")
    pointer = body["output"]["evidence_usage_attestation"]["authoring_artifact"]
    pointer[field] = {
        "logical_artifact_id": "artifact_" + "f" * 32,
        "revision_id": "rev_" + "f" * 32,
        "content_hash": "sha256:" + "f" * 64,
        "result_schema": "authoring-result@12.0",
    }[field]
    with pytest.raises(INVALID):
        _project(_review(case, body))


def test_raw_role_hash_is_not_recomputed_from_normalized_pydantic_serialization():
    case = registered_review_case()
    evidence = case.basis.review_evidence.model_dump(mode="json")
    evidence["authoring"]["artifact"]["sha256"] = "sha256:" + "f" * 64
    body = case.review.model_dump(mode="json")
    body["output"]["evidence_usage_attestation"]["authoring_artifact"]["content_hash"] = (
        "sha256:" + "f" * 64
    )
    review = type(case.review).model_validate(body)
    evidence["review"]["artifact"]["sha256"] = "sha256:" + "e" * 64
    evidence["evidence_sha256"] = content_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    checked = RegisteredItemReviewSolutionEvidence.model_validate(evidence)
    basis = RegisteredReviewSourceBasis(
        source=checked.source, graph_snapshot=case.basis.graph_snapshot, review_evidence=checked
    )
    assert _project(replace(case, basis=basis, review=review)).source_basis == basis


def test_forged_source_graph_and_evidence_hash_fail_before_projection():
    case = registered_review_case()
    for basis in (
        case.basis.model_copy(
            update={"source": case.basis.source.model_copy(update={"source_class": "PAST_EXAM"})}
        ),
        case.basis.model_copy(
            update={
                "graph_snapshot": case.basis.graph_snapshot.model_copy(
                    update={"manifest_sha256": "sha256:" + "f" * 64}
                )
            }
        ),
        case.basis.model_copy(
            update={
                "review_evidence": case.basis.review_evidence.model_copy(
                    update={"evidence_sha256": "sha256:" + "0" * 64}
                )
            }
        ),
    ):
        with pytest.raises(INVALID):
            _project(replace(case, basis=basis))


@pytest.mark.parametrize(
    "timestamp",
    (datetime(2026, 10, 19), datetime(2026, 10, 19, tzinfo=timezone(timedelta(hours=9)))),
)
def test_non_utc_projection_timestamp_is_rejected(timestamp):
    case = registered_review_case()
    with pytest.raises(INVALID):
        project_registered_review_solution(
            source_basis=case.basis,
            authoring=case.authoring,
            review=case.review,
            created_at=timestamp,
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("facet", "DECISIVE_INFERENCE"),
        ("node_ids", []),
        ("reasoning_step_ids", []),
        ("text", "x" * 4001),
    ),
)
def test_claim_never_accepts_invented_legacy_reasoning_or_truncates(field, value):
    original = registered_review_profile()
    claim = original.claims[0].model_copy(update={field: value})
    with pytest.raises(INVALID):
        RegisteredReviewClaim.model_validate(claim)


@pytest.mark.parametrize(
    "change",
    (
        "missing_choice",
        "missing_answer",
        "duplicate",
        "missing_limit",
        "hash",
        "revision",
        "reordered",
    ),
)
def test_profile_closure_rejects_forged_frozen_coverage_hash_and_identity(change):
    original = registered_review_profile()
    body = original.model_dump(mode="json")
    if change == "missing_choice":
        body["claims"] = [
            claim
            for claim in body["claims"]
            if not (claim["kind"] == "CHOICE_DIAGNOSTIC" and claim["subject"] == "①")
        ]
    elif change == "missing_answer":
        body["claims"] = [claim for claim in body["claims"] if claim["kind"] != "ANSWER_SUMMARY"]
    elif change == "duplicate":
        body["claims"].append(copy.deepcopy(body["claims"][0]))
    elif change == "missing_limit":
        body["limitations"] = [REVIEW_PIXEL_LIMITATION]
    elif change == "hash":
        body["profile_sha256"] = "sha256:" + "0" * 64
    elif change == "revision":
        body["profile_revision_id"] = "inferenceprofilerev_" + "0" * 32
    else:
        body["claims"].reverse()
    with pytest.raises(INVALID):
        RegisteredReviewProfile.model_validate(body)


def test_legacy_profile_is_a_distinct_unchanged_contract():
    legacy = profile()
    before = canonical_json_bytes(legacy)
    current = registered_review_profile()
    with pytest.raises(INVALID):
        RegisteredReviewProfile.model_validate(legacy.model_dump(mode="json"))
    with pytest.raises(INVALID):
        InferenceTransferProfile.model_validate(current.model_dump(mode="json"))
    assert canonical_json_bytes(legacy) == before


def test_contract_dependency_direction_has_no_workflow_infrastructure_import():
    tree = ast.parse(
        (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/registered_review_profile.py"
        ).read_bytes()
    )
    assert all(
        not (node.module or "").startswith(
            ("eom_workflow", "eom_orchestrator", "eom_catalog_service", "sqlalchemy")
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )


def test_all_features_remain_concrete_text_not_generic_operation_codes():
    current = registered_review_profile()
    text = registered_review_profile_text(current)
    assert all(claim.text in text for claim in current.claims)
    assert "INTERPRET_GIVEN" not in text and "DECISIVE_INFERENCE" not in text
    changed = build_registered_review_profile(
        source_basis=current.source_basis,
        claims=current.claims,
        created_at=NOW + timedelta(seconds=1),
    )
    assert changed.profile_id == current.profile_id
    assert changed.profile_revision_id != current.profile_revision_id
    assert registered_review_profile_text(changed) == text
