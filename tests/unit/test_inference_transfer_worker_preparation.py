from __future__ import annotations

from eom_catalog_service.inference_transfer_comparison import prepare_pair_comparison
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
)
from eom_identifiers import sha256_bytes

from tests.unit.inference_transfer_fixtures import profile, request


def test_worker_envelope_reuses_one_core_comparison_prompt_with_separate_full_hash() -> None:
    left, right = profile("a"), profile("b")
    comparison = request(left, right)
    core = prepare_pair_comparison(comparison, left=left, right=right)
    prepared = prepare_inference_transfer_worker_comparison(comparison, left=left, right=right)
    assert prepared.prompt_text.startswith(core.prompt_text)
    assert prepared.core_prompt_sha256 == core.prompt_sha256
    assert prepared.prompt_sha256 == sha256_bytes(prepared.prompt_text.encode("utf-8"))
    assert prepared.prompt_sha256 != prepared.core_prompt_sha256
    assert "workflow-role/1.29.0" in prepared.prompt_text
    assert prepared.request.comparison == comparison
    assert prepared.context_bytes < 64 * 1024
    assert "PairComparisonResult" in prepared.prompt_text
