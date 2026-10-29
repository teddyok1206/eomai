"""Family-neutral input with exact, separate source proof and numerical purpose."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_text import build_public_solution_text
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import embedding_space
from tests.unit.inference_transfer_fixtures import profile
from tests.unit.test_creative_registered_report import proposal


def public_recipe():
    value = {
        key: field.default
        for key, field in PublicSolutionEmbeddingRecipe.model_fields.items()
        if key != "recipe_sha256"
    }
    return PublicSolutionEmbeddingRecipe.model_validate(
        value | {"recipe_sha256": content_sha256(value)}
    )


def public_entry(*, creative=False, text="속도는 -36 km/h이고 합력은 0 N이 아니다."):
    basis = profile().source_basis
    source = basis.source.model_dump(mode="json")
    evidence = {"kind": "ACCEPTED_SOLUTION_ANALYSIS", "solution": basis.solution_evidence}
    if creative:
        resolved, lineage = proposal()
        source["source_class"] = "APPROVED_ITEM"
        evidence = {
            "kind": "REGISTERED_CREATIVE_SOURCE_REPORT",
            "lineage": {
                "artifact_id": "artifact_" + "1" * 32,
                "artifact_revision_id": "rev_" + "2" * 32,
                "member_path": "lineage.json",
                "schema_ref": "eom://schemas/external-item/creative-source-lineage/1.0",
                "media_type": "application/json",
                "sha256": content_sha256(lineage.model_dump(mode="json")),
            },
            "lineage_sha256": lineage.lineage_sha256,
            "role_result": resolved.pointer,
            "result_id": lineage.result_id,
            "result_sha256": lineage.result_sha256,
        }
    value = {
        "schema_version": "public-solution-embedding-entry/1.0",
        "source": source,
        "base_analysis_run_id": basis.solution_evidence.base_analysis_run_id,
        "graph_snapshot": basis.graph_snapshot,
        "policy_revision_id": "accessrev_" + "a" * 32,
        "policy_sha256": "sha256:" + "b" * 64,
        "recipe": public_recipe(),
        "evidence": evidence,
        "public_solution": build_public_solution_text(() if text is None else (text,)),
    }
    return PublicSolutionEmbeddingEntry.model_validate(
        value | {"entry_sha256": content_sha256(value)}
    )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("purpose", ["QUERY", "DOCUMENT"])
def test_same_public_text_encodes_identically_without_merging_evidence(device, purpose):
    past, creative = public_entry(), public_entry(creative=True)
    before = tuple(canonical_json_bytes(value) for value in (past, creative))
    space = embedding_space(device=device, purpose=purpose)
    inputs = tuple(
        prepare_public_solution_encoding(entry, space=space, storage_partition="public-solution")
        for entry in (past, creative)
    )
    assert inputs[0].input == inputs[1].input
    assert inputs[0].input.text == past.public_solution.text == creative.public_solution.text
    assert inputs[0].source.entry_sha256 != inputs[1].source.entry_sha256
    assert inputs[0].source.evidence.kind != inputs[1].source.evidence.kind
    assert inputs[0].input.encoding.space_sha256 == space.space_sha256
    assert before == tuple(canonical_json_bytes(value) for value in (past, creative))


def test_query_and_document_keep_exact_public_text_but_not_numeric_space_identity():
    entry = public_entry()
    values = tuple(
        prepare_public_solution_encoding(
            entry, space=embedding_space(purpose=purpose), storage_partition="public-solution"
        ).input
        for purpose in ("QUERY", "DOCUMENT")
    )
    assert values[0].text == values[1].text
    assert values[0].encoding != values[1].encoding


@pytest.mark.parametrize("creative", [False, True])
def test_missing_and_oversized_reasoning_never_become_a_fabricated_or_cut_input(creative):
    for text, reason in (
        (None, "MISSING_PUBLIC_SOLUTION"),
        ("가" * 87382 + "보존되지 않는다.", "PUBLIC_SOLUTION_TEXT_LIMIT"),
    ):
        entry = public_entry(creative=creative, text=text)
        result = prepare_public_solution_encoding(
            entry, space=embedding_space(), storage_partition="public-solution"
        )
        assert result.input is None and result.unavailable_reason == reason
        assert result.source == entry


@pytest.mark.parametrize("creative", [False, True])
def test_forged_text_and_nested_recipe_are_revalidated(creative):
    entry = public_entry(creative=creative)
    for changed in (
        entry.model_copy(
            update={"public_solution": entry.public_solution.model_copy(update={"text": "改"})}
        ),
        entry.model_copy(
            update={"recipe": entry.recipe.model_copy(update={"facets": "EXACT_PROFILE_CLAIMS"})}
        ),
    ):
        with pytest.raises(ValueError):
            prepare_public_solution_encoding(
                changed, space=embedding_space(), storage_partition="public-solution"
            )


def test_creative_source_cannot_impersonate_past_or_dereference_arbitrary_members():
    value = public_entry(creative=True).model_dump(mode="json")
    for field in ("source_class", "member_path", "schema_ref"):
        changed = deepcopy(value)
        if field == "source_class":
            changed["source"][field] = "PAST_EXAM"
        else:
            changed["evidence"]["role_result"][field] = "other"
        changed["entry_sha256"] = content_sha256(
            {key: item for key, item in changed.items() if key != "entry_sha256"}
        )
        with pytest.raises(ValueError):
            PublicSolutionEmbeddingEntry.model_validate(changed)


def test_accepted_solution_base_cannot_be_rebound_to_a_different_analysis():
    value = public_entry().model_dump(mode="json")
    value["base_analysis_run_id"] = "analysisrun_" + "f" * 32
    value["entry_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "entry_sha256"}
    )
    with pytest.raises(ValueError, match="BASE_ANALYSIS_MISMATCH"):
        PublicSolutionEmbeddingEntry.model_validate(value)


def test_new_recipe_is_not_a_reinterpretation_of_released_v1_recipe():
    from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe

    with pytest.raises(ValueError):
        ExperimentViewRecipe.model_validate(public_recipe().model_dump(mode="json"))


def test_new_schema_is_pinned_packaged_and_validated_as_2020_12():
    root = Path(__file__).resolve().parents[2]
    name = "knowledge/public-solution-embedding-entry-v1.schema.json"
    assert (root / "schemas" / name).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    ).read_bytes()
    schema = load_schema("public-solution-embedding-entry-v1")
    Draft202012Validator.check_schema(schema)
    for entry in (public_entry(), public_entry(creative=True)):
        validate_contract("public-solution-embedding-entry-v1", entry.model_dump(mode="json"))
        assert PublicSolutionEmbeddingEntry.model_validate_json(entry.model_dump_json()) == entry
