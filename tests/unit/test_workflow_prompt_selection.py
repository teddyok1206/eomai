from pathlib import Path

from eom_workflow import (
    KnowledgeAnalysisWorkerRequest,
    LegacyItemEditorialCompatibilityWorkerRequest,
    LegacyItemExtractionWorkerRequest,
    WorkerRequest,
)
from eom_workflow_runner.engine import _prompt_name_for_request

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_extraction_typed_request_uses_dedicated_prompt() -> None:
    request = LegacyItemExtractionWorkerRequest.model_construct(extraction_request=None)

    assert (
        _prompt_name_for_request(worker_role="support", request=request) == "legacy-item-extraction"
    )


def test_legacy_extraction_prompt_requires_title_and_body_anchor_coverage() -> None:
    prompt = (ROOT / "content/prompt-templates/placeholders/legacy-item-extraction.txt").read_text(
        encoding="utf-8"
    )

    assert "`content_path` is exactly `title` first" in prompt
    assert "`content_path` begins with `body[`" in prompt
    assert "first finish that item's unique" in prompt
    assert "every value must byte-for-byte equal an `anchor_id`" in prompt
    assert "Never invent an anchor ID or reuse one from another item" in prompt


def test_editorial_compatibility_uses_only_its_team_authority_prompt() -> None:
    request = LegacyItemEditorialCompatibilityWorkerRequest.model_construct(
        compatibility_request=None
    )

    assert _prompt_name_for_request(worker_role="support", request=request) == (
        "legacy-item-editorial-compatibility"
    )
    prompt = (
        ROOT / "content/prompt-templates/placeholders/legacy-item-editorial-compatibility.txt"
    ).read_text(encoding="utf-8")
    assert "Read both authority documents in full" in prompt
    assert "do not invent, add, or silently import EOM editorial" in " ".join(prompt.split())


def test_other_support_requests_keep_existing_support_prompt() -> None:
    knowledge_request = KnowledgeAnalysisWorkerRequest.model_construct(analysis_request=None)
    placeholder_request = WorkerRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")

    assert _prompt_name_for_request(worker_role="support", request=knowledge_request) == "support"
    assert _prompt_name_for_request(worker_role="support", request=placeholder_request) == "support"


def test_item_management_keeps_registration_prompt_alias() -> None:
    request = WorkerRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")

    assert (
        _prompt_name_for_request(worker_role="item_management", request=request) == "registration"
    )
