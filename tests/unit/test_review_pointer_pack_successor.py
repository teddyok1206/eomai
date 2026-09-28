from __future__ import annotations

from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _local_image_prompt_contract,
)
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.1"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.2"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_review_pointer_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)
    assert predecessor.manifest.pack.version == "1.20.1"
    assert pack.manifest.pack.version == "1.20.2"
    assert pack.manifest.compatibility == predecessor.manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item",
        "1.20.2",
        request,
    )


def test_successor_changes_only_pack_review_profile_and_review_prompt() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/review.md"),
    }
    prompt = (PACK / "prompt-templates/review.md").read_text(encoding="utf-8")
    for requirement in (
        "`answer`, `bottom_stem`, `choices`, `explanations`, `inquiry`, `labeled_blocks`",
        "`metadata`, `schema_version`, `item_number`",
        "`/metadata/subject`를 만들지 말고",
        "primitive scalar leaf",
        "`source.source_class`의 정렬·중복 제거된 집합과 정확히",
        "`evidence_status=INSUFFICIENT`",
    ):
        assert requirement in prompt


def test_successor_preserves_minimal_line_art_prompt_contract() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.2"}}
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_MINIMAL_LINE_ART_V2"
