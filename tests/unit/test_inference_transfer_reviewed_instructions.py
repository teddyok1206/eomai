"""Durable reviewed prompts protect the existing machine/human trust boundary."""

from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_workflow.inference_transfer_bootstrap_contract import (
    MAX_TRANSFER_INSTRUCTION_BYTES,
    InferenceTransferReviewedInstructionMember,
)

_ROOT = Path(__file__).resolve().parents[2]
_INSTRUCTIONS = _ROOT / "config/control-plane/item-inference-transfer-comparison-v1/instructions"


def test_reviewed_members_have_the_exact_bootstrap_purpose() -> None:
    for layer, name in (("PLATFORM", "platform.md"), ("ROLE", "transfer-rubric.md")):
        payload = (_INSTRUCTIONS / name).read_bytes()
        assert 0 < len(payload) <= MAX_TRANSFER_INSTRUCTION_BYTES
        payload.decode("utf-8")
        member = InferenceTransferReviewedInstructionMember.model_validate(
            {
                "layer": layer,
                "relative_path": f"instructions/{name}",
                "logical_name": f"instructions/{name}",
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
            }
        )
        assert member.sha256 == sha256_bytes(payload)


def test_rubric_requires_decisive_correspondence_and_separate_differences() -> None:
    text = (_INSTRUCTIONS / "transfer-rubric.md").read_text(encoding="utf-8")
    for required in (
        "A_TO_B",
        "GIVEN_CONDITION",
        "INTERMEDIATE_RELATION",
        "DECISIVE_INFERENCE",
        "ASKED_JUDGEMENT",
        "MISCONCEPTION",
        "INSUFFICIENT",
        "NO_TRANSFER",
        "STRUCTURAL_ANALOGY",
        "NEAR_IDENTICAL_CANDIDATE",
        "differences",
        "new_reasoning",
        "selected claim",
        "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION",
        "자료 해석 → 관계 도출 → ㄱㄴㄷ 판단",
    ):
        assert required in text


def test_platform_preserves_worker_isolation_and_real_hash_calculation() -> None:
    text = (_INSTRUCTIONS / "platform.md").read_text(encoding="utf-8")
    for required in (
        "비신뢰",
        "staged local input",
        "workflow-role/1.29.0",
        "item-inference-transfer-pair-result/1.0",
        "latest",
        "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION",
        "canonical JSON",
        "추측하지 않는다",
        "실제 UTC",
    ):
        assert required in text
