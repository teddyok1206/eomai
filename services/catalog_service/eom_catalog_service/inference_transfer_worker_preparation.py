"""Prepare a bounded generic worker envelope without starting an execution."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    PairComparisonRequest,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.inference_transfer import InferenceTransferPairWorkerRequest

from eom_catalog_service.inference_transfer_comparison import prepare_pair_comparison

WORKER_PROMPT_VERSION = "item-inference-transfer-worker-envelope/1.0"
_ENVELOPE_INSTRUCTIONS = """
이번 실행에서는 앞서 지정한 PairComparisonResult를 output으로 넣은
workflow-role/1.29.0 support RoleResult JSON 하나만 반환한다.
Orchestrator가 제공한 구조화 출력 스키마의 job/workflow/step/artifact identity를 그대로 쓴다.
schema_version=1.0, protocol_version=workflow-role/1.29.0, role=support, status=ok이다.
completed_at은 실제 UTC 시각을 사용한다. output에는 비교 결과 외의 내용을 넣지 않는다.
output.result_sha256은 result_sha256만 제외한 output의 canonical JSON
(UTF-8, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
SHA-256에 sha256: 접두어를 붙인다. 해시는 추측하지 말고 로컬 계산으로 확인한다.
worker는 제공된 작은 JSON만 읽고 결과를 로컬 제출한다. DB/NAS/네트워크 접근은 금지한다.
"""


@dataclass(frozen=True)
class PreparedTransferWorkerComparison:
    request: InferenceTransferPairWorkerRequest
    prompt_version: str
    core_prompt_sha256: str
    prompt_text: str
    prompt_sha256: str
    context_bytes: int


def prepare_inference_transfer_worker_comparison(
    comparison: PairComparisonRequest,
    *,
    left: InferenceTransferProfile,
    right: InferenceTransferProfile,
) -> PreparedTransferWorkerComparison:
    """Accept already authorized exact profiles; this is not an execution/permission grant."""

    request = InferenceTransferPairWorkerRequest(
        comparison=comparison, left_profile=left, right_profile=right
    )
    core = prepare_pair_comparison(comparison, left=left, right=right)
    prompt = core.prompt_text + _ENVELOPE_INSTRUCTIONS
    return PreparedTransferWorkerComparison(
        request=request,
        prompt_version=WORKER_PROMPT_VERSION,
        core_prompt_sha256=core.prompt_sha256,
        prompt_text=prompt,
        prompt_sha256=sha256_bytes(prompt.encode("utf-8")),
        context_bytes=len(canonical_json_bytes(request.model_dump(mode="json"))),
    )
