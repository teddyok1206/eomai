"""Same numeric inputs, distinct exact provenance; no live model or storage calls."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
    parse_public_solution_encoding_entry,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import embedding_space
from tests.unit.test_public_solution_encoding import public_entry
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value
from tests.unit.test_registered_item_solution_analysis_models import result_value


def registered_entry():
    value = public_entry().model_dump(mode="json")
    request, result = request_value(), result_value()
    pointer = deepcopy(value["evidence"]["solution"])
    pointer.update(
        schema_version="registered-item-solution-evidence-pointer/1.0",
        base_analysis_run_id=request["base_analysis"]["analysis_run_id"],
        base_analysis_result_id=request["base_analysis"]["analysis_result_id"],
        solution_analysis_run_id="analysisrun_" + "f" * 32,
        solution_analysis_result_id=result["analysis_result_id"],
        solution_result_sha256=result["result_sha256"],
    )
    pointer["accepted_result_artifact"].update(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "a" * 32,
        schema_ref="eom://schemas/knowledge/knowledge-analysis-result/11.0",
        sha256=content_sha256(result),
    )
    for name in ("proposal_receipt", "solution_report"):
        pointer[name].update(
            artifact_id="artifact_" + "c" * 32, artifact_revision_id="rev_" + "c" * 32
        )
    pointer["proposal_receipt"]["schema_ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/10.0"
    )
    pointer["pointer_sha256"] = content_sha256(
        {key: item for key, item in pointer.items() if key != "pointer_sha256"}
    )
    value.update(
        schema_version="public-solution-embedding-entry/2.0",
        source=request["source"],
        base_analysis_run_id=pointer["base_analysis_run_id"],
        evidence={"kind": "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS", "solution": pointer},
    )
    return RegisteredPublicSolutionEmbeddingEntry.model_validate(rehash(value))


def rehash(value):
    evidence = value["evidence"]["solution"]
    evidence["pointer_sha256"] = content_sha256(
        {key: item for key, item in evidence.items() if key != "pointer_sha256"}
    )
    value["entry_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "entry_sha256"}
    )
    return value


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("purpose", ["QUERY", "DOCUMENT"])
def test_past_creative_ai_have_identical_encoding_identity_for_the_same_public_text(
    device, purpose
):
    entries = (public_entry(), public_entry(creative=True), registered_entry())
    before = tuple(canonical_json_bytes(entry) for entry in entries)
    inputs = tuple(
        prepare_public_solution_encoding(
            entry,
            space=embedding_space(device=device, purpose=purpose),
            storage_partition="public-solution",
        )
        for entry in entries
    )
    assert inputs[0].input == inputs[1].input == inputs[2].input
    assert len({entry.entry_sha256 for entry in entries}) == 3
    assert len({entry.evidence.kind for entry in entries}) == 3
    assert before == tuple(canonical_json_bytes(entry) for entry in entries)
    assert entries[2].recipe == entries[0].recipe
    assert (
        entries[2].evidence.solution.solution_result_sha256
        != entries[2].evidence.solution.accepted_result_artifact.sha256
    )


@pytest.mark.parametrize(
    "change",
    [
        "past_source",
        "past_result",
        "past_receipt",
        "foreign_report_revision",
        "foreign_base",
        "same_run",
        "same_result",
        "extra",
        "coerced_kind",
        "missing_schema",
        "future_version",
    ],
)
def test_wrong_family_pointer_or_identity_is_rejected_even_after_outer_hash_recomputation(change):
    value = registered_entry().model_dump(mode="json")
    pointer = value["evidence"]["solution"]
    if change == "past_source":
        value["source"]["source_class"] = "PAST_EXAM"
    elif change == "past_result":
        pointer["accepted_result_artifact"]["schema_ref"] = (
            "eom://schemas/knowledge/knowledge-analysis-result/10.0"
        )
    elif change == "past_receipt":
        pointer["proposal_receipt"]["schema_ref"] = (
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0"
        )
    elif change == "foreign_report_revision":
        pointer["solution_report"]["artifact_revision_id"] = "rev_" + "d" * 32
    elif change == "foreign_base":
        value["base_analysis_run_id"] = "analysisrun_" + "d" * 32
    elif change == "same_run":
        pointer["solution_analysis_run_id"] = pointer["base_analysis_run_id"]
    elif change == "same_result":
        pointer["solution_analysis_result_id"] = pointer["base_analysis_result_id"]
    elif change == "extra":
        value["review_conclusion"] = "not a substitute for a full solution"
    elif change == "coerced_kind":
        value["evidence"]["kind"] = 1
    elif change == "missing_schema":
        del pointer["solution_report"]["schema_ref"]
    else:
        value["schema_version"] = "public-solution-embedding-entry/3.0"
    with pytest.raises(ValueError):
        parse_public_solution_encoding_entry(rehash(value))


def test_forged_nested_semantic_hashes_are_not_admitted_to_the_encoder():
    entry = registered_entry()
    for changed in (
        entry.model_copy(
            update={
                "public_solution": entry.public_solution.model_copy(update={"text": "다른 풀이"})
            }
        ),
        entry.model_copy(
            update={
                "recipe": entry.recipe.model_copy(update={"recipe_sha256": "sha256:" + "0" * 64})
            }
        ),
        entry.model_copy(
            update={
                "evidence": entry.evidence.model_copy(
                    update={
                        "solution": entry.evidence.solution.model_copy(
                            update={"solution_result_sha256": "sha256:" + "0" * 64}
                        )
                    }
                )
            }
        ),
    ):
        with pytest.raises(ValueError):
            prepare_public_solution_encoding(
                changed, space=embedding_space(), storage_partition="public-solution"
            )


def test_new_entry_does_not_change_historical_entry1_parser_or_imply_runtime_admission():
    entry = registered_entry()
    with pytest.raises(ValueError):
        PublicSolutionEmbeddingEntry.model_validate(entry.model_dump(mode="json"))
    from eom_catalog_contracts.embedding_index_families import parse_supported_embedding_entry

    # Metadata parsing is not a runtime permission/activation grant. Native
    # request/plan schemas still select their own exact supported family.
    assert parse_supported_embedding_entry(entry) == entry


def test_candidate_schema_is_closed_packaged_and_round_trips():
    root = Path(__file__).resolve().parents[2]
    relative = "knowledge/public-solution-embedding-entry-v2.schema.json"
    assert (root / "schemas" / relative).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
    ).read_bytes()
    Draft202012Validator.check_schema(load_schema("public-solution-embedding-entry-v2"))
    entry = registered_entry()
    validate_contract("public-solution-embedding-entry-v2", entry.model_dump(mode="json"))
    assert (
        RegisteredPublicSolutionEmbeddingEntry.model_validate_json(entry.model_dump_json()) == entry
    )
