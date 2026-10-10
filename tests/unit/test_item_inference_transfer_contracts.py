from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import load_schema, validate_contract
from eom_catalog_contracts.item_inference_transfer import (
    HumanTransferEvaluation,
    InferenceTransferClaim,
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
    PairComparisonRequest,
    PairComparisonResult,
    validate_inference_transfer_profile_references,
    validate_pair_comparison_references,
    validate_pair_comparison_request_references,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import (
    embedding_model,
    profile,
    report,
    request,
    result,
    sha,
)


def _seal(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = content_sha256({key: item for key, item in value.items() if key != field})
    return value


def test_additive_schema_is_package_owned_and_canonical_mirror_is_identical() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = load_schema("item-inference-transfer")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert (root / "schemas/knowledge/item-inference-transfer-v1.schema.json").read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
        "item-inference-transfer-v1.schema.json"
    ).read_bytes()


def test_exact_profile_pointer_names_a_registered_schema_family() -> None:
    exact = InferenceTransferProfilePointer.from_profile(profile())
    assert exact.schema_ref == load_schema("item-inference-transfer")["$id"]
    assert profile().schema_version == "item-inference-transfer-profile/1.0"


@pytest.mark.parametrize("factory", [profile, request, result, embedding_model])
def test_schema_and_frozen_models_accept_representative_contracts(factory: Any) -> None:
    parsed = factory()
    validate_contract("item-inference-transfer", parsed.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="frozen"):
        parsed.schema_version = "tampered"


def test_claim_retains_negation_numbers_units_and_not_only_generic_step_operations() -> None:
    no_friction = profile(
        "a", condition="마찰이 없고 속력은 36 km/h이다.", inference="에너지 합은 일정하다."
    )
    friction = profile(
        "b", condition="마찰이 있고 속력은 10 m/s이다.", inference="마찰이 한 일을 빼야 한다."
    )
    assert no_friction.claims[0].text == "마찰이 없고 속력은 36 km/h이다."
    assert friction.claims[0].text == "마찰이 있고 속력은 10 m/s이다."
    assert no_friction.claims[1].text != friction.claims[1].text
    assert no_friction.profile_sha256 != friction.profile_sha256


@pytest.mark.parametrize(
    "condition,inference",
    [
        (
            "병렬 용수철은 변형량이 같고 힘의 합이 전체 힘이다.",
            "F=kx와 공통 x로 각 힘의 비를 찾는다.",
        ),
        (
            "직렬 용수철은 힘이 같고 변형량의 합이 전체 변형량이다.",
            "F=kx와 공통 F로 각 변형량의 비를 찾는다.",
        ),
        (
            "병렬 저항은 전압이 같고 전류의 합이 전체 전류이다.",
            "V=IR와 공통 V로 각 전류의 비를 찾는다.",
        ),
    ],
)
def test_same_generic_operations_do_not_replace_specific_condition_and_inference(
    condition: str, inference: str
) -> None:
    baseline = report()
    actual = report(condition, inference)
    assert tuple(step.operation for step in actual.solution_steps) == tuple(
        step.operation for step in baseline.solution_steps
    )
    derived = profile(condition=condition, inference=inference)
    assert derived.claims[0].text == condition
    assert derived.claims[1].text == inference
    assert "human_pass" not in derived.model_dump()


def test_missing_report_does_not_fabricate_a_grounded_profile() -> None:
    value = profile().model_dump(mode="json")
    value["source_basis"]["solution_evidence"] = None
    with pytest.raises(ValidationError):
        InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))


@pytest.mark.parametrize("field", ["reasoning_step_ids", "node_ids", "anchor_ids"])
def test_claim_rejects_duplicate_and_unsorted_reference_ids(field: str) -> None:
    value = profile().claims[0].model_dump(mode="json")
    value[field] = [value[field][0], value[field][0]]
    with pytest.raises(ValidationError, match="sorted and unique"):
        InferenceTransferClaim.model_validate(value)


@pytest.mark.parametrize(
    "field,unknown",
    [
        ("reasoning_step_ids", "solutionstep_unknown"),
        ("node_ids", "knode_concept_foreign"),
        ("anchor_ids", "anchor_foreign"),
    ],
)
def test_profile_rejects_unresolved_report_references(field: str, unknown: str) -> None:
    value = profile().model_dump(mode="json")
    value["claims"][0][field] = [unknown]
    parsed = InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))
    with pytest.raises(ValueError, match=r"unknown|outside"):
        validate_inference_transfer_profile_references(parsed, report())


def test_profile_reference_closure_uses_exact_base_and_selected_steps() -> None:
    validate_inference_transfer_profile_references(profile(), report())
    wrong = report().model_copy(
        update={"base_analysis_result_id": "knowledgeanalysisresult_" + "f" * 32}
    )
    with pytest.raises(ValueError, match="different accepted bases"):
        validate_inference_transfer_profile_references(profile(), wrong)


def test_profiles_hash_all_pins_and_require_honest_limitations() -> None:
    value = profile().model_dump(mode="json")
    value["claims"][0]["text"] = "changed"
    with pytest.raises(ValidationError, match="canonical content"):
        InferenceTransferProfile.model_validate(value)
    value = profile().model_dump(mode="json")
    value["limitations"] = []
    with pytest.raises(ValidationError, match="explicit limitation"):
        InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))
    with pytest.raises(SchemaValidationError):
        validate_contract("item-inference-transfer", value)
    value["claims"] = []
    with pytest.raises(ValidationError, match="explicit limitation"):
        InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))


def test_no_permission_hidden_reasoning_or_human_pass_can_be_injected() -> None:
    for key in ("permissions", "hidden_chain_of_thought", "human_pass"):
        value = profile().model_dump(mode="json")
        value[key] = "ADMIN"
        with pytest.raises(ValidationError, match="Extra inputs"):
            InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))
        with pytest.raises(SchemaValidationError):
            validate_contract("item-inference-transfer", value)


def test_deterministic_projection_cannot_invent_model_prompt_provenance() -> None:
    value = profile().model_dump(mode="json")
    value["extraction"]["prompt_sha256"] = sha()
    with pytest.raises(ValidationError, match="must not invent"):
        InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))
    value["extraction"]["method"] = "CODEX_DERIVED"
    with pytest.raises(ValidationError, match="requires prompt"):
        InferenceTransferProfile.model_validate(_seal(value, "profile_sha256"))


def test_pair_requires_condition_and_decisive_mapping_not_generic_dag_similarity() -> None:
    parsed = result()
    validate_pair_comparison_references(request(), parsed, profile("a"), profile("b"))
    value = parsed.model_dump(mode="json")
    value["mappings"] = value["mappings"][:1]
    with pytest.raises(ValidationError, match="condition and decisive"):
        PairComparisonResult.model_validate(_seal(value, "result_sha256"))
    with pytest.raises(SchemaValidationError):
        validate_contract("item-inference-transfer", value)


def test_pair_rejects_unselected_claim_wrong_facet_and_stale_exact_profile() -> None:
    original = result().model_dump(mode="json")
    value = deepcopy(original)
    value["mappings"][0]["left_claim_ids"] = ["transferclaim_unknown"]
    parsed = PairComparisonResult.model_validate(_seal(value, "result_sha256"))
    with pytest.raises(ValueError, match="unresolved"):
        validate_pair_comparison_references(request(), parsed, profile("a"), profile("b"))
    value = deepcopy(original)
    value["mappings"][0]["left_claim_ids"] = ["transferclaim_decisive"]
    parsed = PairComparisonResult.model_validate(_seal(value, "result_sha256"))
    with pytest.raises(ValueError, match="mismatched transfer facet"):
        validate_pair_comparison_references(request(), parsed, profile("a"), profile("b"))
    changed = profile("a", condition="다른 조건", inference="다른 추론")
    with pytest.raises(ValueError, match="exact profiles differ"):
        validate_pair_comparison_references(request(), result(), changed, profile("b"))


def test_pair_insufficient_does_not_fabricate_mapping_or_human_success() -> None:
    value = result().model_dump(mode="json")
    value.update(
        {
            "judgement": "INSUFFICIENT",
            "mappings": [],
            "shared_idea": None,
            "limitations": ["구체적인 핵심 관계를 보고서에서 확인할 수 없다."],
        }
    )
    parsed = PairComparisonResult.model_validate(_seal(value, "result_sha256"))
    validate_contract("item-inference-transfer", parsed.model_dump(mode="json"))
    assert parsed.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    assert "human_pass" not in parsed.model_dump()


def test_pair_identical_snapshot_and_request_hash_tampering_are_explicit_errors() -> None:
    value = request().model_dump(mode="json")
    value["right_profile"] = value["left_profile"]
    with pytest.raises(ValidationError, match="two different"):
        PairComparisonRequest.model_validate(_seal(value, "request_sha256"))
    value = request().model_dump(mode="json")
    value["left_claim_ids"] = []
    with pytest.raises(ValidationError, match="canonical content"):
        PairComparisonRequest.model_validate(value)


def test_request_context_rechecks_hash_even_if_internal_model_copy_bypassed_validation() -> None:
    left, right = profile("a"), profile("b")
    query = request(left, right)
    changed = left.model_copy(update={"limitations": ("changed after hash",)})
    with pytest.raises(ValueError, match="canonical content"):
        validate_pair_comparison_request_references(query, changed, right)


def test_duplicate_correspondence_with_different_mapping_id_is_rejected() -> None:
    value = result().model_dump(mode="json")
    copy = deepcopy(value["mappings"][0])
    copy["mapping_id"] = "transfermapping_duplicate"
    value["mappings"].append(copy)
    value["mappings"].sort(key=lambda mapping: mapping["mapping_id"])
    with pytest.raises(ValidationError, match="duplicate the same correspondence"):
        PairComparisonResult.model_validate(_seal(value, "result_sha256"))


def test_human_label_requires_identity_exact_profiles_and_actual_help_location() -> None:
    pair = request().model_dump(mode="json")
    value = {key: pair[key] for key in ("left_profile", "right_profile", "direction", "rubric")}
    value.update(
        {
            "schema_version": "item-inference-transfer-human-evaluation/1.0",
            "evaluation_id": "transferevaluation_" + "a" * 32,
            "evaluation_revision_id": "transferevaluationrev_" + "b" * 32,
            "reviewer_id": "teacher-a",
            "label": "CRUX_TRANSFERS",
            "where_helped": [],
            "reason": "첫 문제에서 보존 조건을 찾는 착상이 두 번째 문제에서 도움이 됐다.",
            "evaluated_at": "2026-10-10T09:00:00Z",
        }
    )
    with pytest.raises(ValidationError, match="where the first problem helped"):
        HumanTransferEvaluation.model_validate(_seal(value, "evaluation_sha256"))
    value["where_helped"] = ["두 조건을 결합해 일정한 총량을 찾는 부분"]
    parsed = HumanTransferEvaluation.model_validate(_seal(value, "evaluation_sha256"))
    validate_contract("item-inference-transfer", parsed.model_dump(mode="json"))


@pytest.mark.parametrize(
    "repo", ["BAAI/bge-m3", "intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"]
)
def test_embedding_model_recipe_is_pinned_and_non_truncating(repo: str) -> None:
    parsed = embedding_model(repo)
    validate_contract("item-inference-transfer", parsed.model_dump(mode="json"))
    assert parsed.truncation == "REJECT_OVERFLOW"
    value = parsed.model_dump(mode="json")
    value["document_prefix"] = "query: " if repo == "BAAI/bge-m3" else ""
    with pytest.raises(ValidationError, match="recipe differs"):
        LocalEmbeddingModelSpec.model_validate(_seal(value, "manifest_sha256"))
    with pytest.raises(SchemaValidationError):
        validate_contract("item-inference-transfer", value)


@pytest.mark.parametrize(
    "mutation", ["duplicate_file", "missing_weight", "runtime_missing", "model_hash"]
)
def test_embedding_model_rejects_unsafe_incomplete_or_changed_manifest(mutation: str) -> None:
    value = embedding_model().model_dump(mode="json")
    if mutation == "duplicate_file":
        value["files"][-1] = value["files"][0]
    elif mutation == "missing_weight":
        value["files"][1]["member_path"] = "README.md"
        value["files"].sort(key=lambda file: file["member_path"])
    elif mutation == "runtime_missing":
        value["runtime_versions"][0] = value["runtime_versions"][1]
    else:
        value["upstream_revision"] = "f" * 40
    if mutation != "model_hash":
        _seal(value, "manifest_sha256")
    with pytest.raises(ValidationError):
        LocalEmbeddingModelSpec.model_validate(value)
