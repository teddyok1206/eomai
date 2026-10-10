from __future__ import annotations

import json

import pytest
from eom_catalog_contracts.item_inference_transfer import PairComparisonRequest
from eom_catalog_service.inference_transfer_comparison import (
    TransferComparisonError,
    admit_pair_comparison_result,
    prepare_pair_comparison,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.inference_transfer_fixtures import profile, request, result


def test_prepared_prompt_is_exact_bounded_and_deterministic_not_worker_execution() -> None:
    a, b = profile("a"), profile("b")
    query = request(a, b)
    first = prepare_pair_comparison(query, left=a, right=b)
    second = prepare_pair_comparison(query, left=a, right=b)
    assert first == second
    assert first.prompt_sha256 == sha256_bytes(first.prompt_text.encode("utf-8"))
    assert first.context_bytes < 256 * 1024
    assert query.request_sha256 in first.prompt_text
    assert "같은 소재·공식·정답" in first.prompt_text
    assert "외부 API, DB, NAS" in first.prompt_text
    assert "비공개 사고 과정" in first.prompt_text
    context = first.prompt_text.split("BEGIN_UNTRUSTED_COMPARISON_JSON\n", 1)[1]
    context = context.rsplit("\nEND_UNTRUSTED_COMPARISON_JSON", 1)[0]
    assert json.loads(context)["request"] == query.model_dump(mode="json")


def test_wrong_exact_profile_is_rejected_before_prompt_creation() -> None:
    with pytest.raises(TransferComparisonError, match="INPUT_INVALID"):
        prepare_pair_comparison(request(), left=profile("a"), right=profile("c"))


def test_selection_of_a_nonexistent_claim_is_not_silently_dropped() -> None:
    value = request().model_dump(mode="json", exclude={"request_sha256"})
    value["left_claim_ids"] = ["transferclaim_foreign"]
    query = PairComparisonRequest.model_validate({**value, "request_sha256": content_sha256(value)})
    with pytest.raises(TransferComparisonError, match="INPUT_INVALID"):
        prepare_pair_comparison(query, left=profile("a"), right=profile("b"))


def test_grounded_result_is_a_machine_hypothesis_not_human_pass() -> None:
    query = request()
    admitted = admit_pair_comparison_result(
        result(query).model_dump(mode="json"),
        request=query,
        left=profile("a"),
        right=profile("b"),
    )
    assert admitted.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    assert "human_verified" not in admitted.model_dump()


def test_result_cannot_invent_a_foreign_mapped_condition_even_with_valid_hash() -> None:
    value = result().model_dump(mode="json", exclude={"result_sha256"})
    value["mappings"][0]["left_claim_ids"] = ["transferclaim_foreign"]
    value["result_sha256"] = content_sha256(value)
    with pytest.raises(ValueError, match="unresolved claim"):
        admit_pair_comparison_result(
            value, request=request(), left=profile("a"), right=profile("b")
        )


def test_complete_looking_result_with_changed_hash_is_rejected() -> None:
    value = result().model_dump(mode="json")
    value["shared_idea"] = "원래 근거와 다른 주장"
    with pytest.raises(ValueError, match="result_sha256"):
        admit_pair_comparison_result(
            value, request=request(), left=profile("a"), right=profile("b")
        )
