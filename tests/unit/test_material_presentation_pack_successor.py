from __future__ import annotations

from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _local_image_prompt_contract,
)
from eom_workflow.models import WorkflowRequest
from eom_workflow.review_rework import REPAIRABLE_REVIEW_FINDING_CODES
from eom_workflow_runner.models import WorkflowInstanceRecord

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.6"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.7"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_material_presentation_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)
    assert predecessor.manifest.pack.version == "1.20.6"
    assert pack.manifest.pack.version == "1.20.7"
    assert pack.manifest.compatibility == predecessor.manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.7", request
    )


def test_material_presentation_pack_changes_only_owned_prompt_and_profile_files() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
    }
    assert (
        successor[Path("prompt-templates/image.md")]
        == predecessor[Path("prompt-templates/image.md")]
    )


def test_material_presentation_prompts_bind_one_image_as_one_unlabeled_box() -> None:
    authoring = (PACK / "prompt-templates/authoring.md").read_text(encoding="utf-8")
    review = (PACK / "prompt-templates/review.md").read_text(encoding="utf-8")

    assert "`자료와 그림`, `그림과 자료`, `<자료>와 그림`" in authoring
    assert "빈 두 번째 칸이나 `(가)/(나)`를 만들지 않는다" in authoring
    assert "`MATERIAL_PRESENTATION_REDUNDANT`" in review
    assert "IMAGE 두 개" in review
    assert "MATERIAL_PRESENTATION_REDUNDANT" in REPAIRABLE_REVIEW_FINDING_CODES


def test_material_presentation_pack_keeps_reference_composition_prompt_contract() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.7"}}

    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
