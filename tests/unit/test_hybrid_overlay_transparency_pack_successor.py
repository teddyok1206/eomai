from __future__ import annotations

from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _local_image_prompt_contract,
    _uses_v1_reference_conditioning,
)
from eom_image_contracts import LocalImageProviderBinding
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.unit.test_local_image_adapter import _binding_value

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.3"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.4"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_transparent_overlay_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)
    assert predecessor.manifest.pack.version == "1.20.3"
    assert pack.manifest.pack.version == "1.20.4"
    assert pack.manifest.compatibility == predecessor.manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.4", request
    )


def test_successor_changes_only_image_profile_and_prompt() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-stimulus-drawing.yaml"),
        Path("prompt-templates/image.md"),
    }
    prompt = (PACK / "prompt-templates/image.md").read_text(encoding="utf-8")
    for requirement in (
        "투명 캔버스",
        'width="800" height="500"',
        "불투명 배경 도형",
        "참조-conditioned raster를 가려",
        "800x500 RGBA 투명 overlay",
    ):
        assert requirement in prompt


def test_successor_keeps_reference_composition_route() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.4"}}
    binding = LocalImageProviderBinding.model_validate(_binding_value())
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
    assert _uses_v1_reference_conditioning(workflow, binding)
