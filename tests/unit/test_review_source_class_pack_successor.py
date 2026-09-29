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
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.5"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.6"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_review_source_class_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)
    assert predecessor.manifest.pack.version == "1.20.5"
    assert pack.manifest.pack.version == "1.20.6"
    assert pack.manifest.compatibility == predecessor.manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.6", request
    )


def test_review_source_class_pack_changes_only_review_owned_files() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/review.md"),
    }
    for relative_path in (
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/image.md"),
    ):
        assert successor[relative_path] == predecessor[relative_path]


def test_review_prompt_binds_source_classes_to_manifest_literals() -> None:
    profile = (PACK / "profiles/generated-knowledge-review.yaml").read_text(encoding="utf-8")
    prompt = (PACK / "prompt-templates/review.md").read_text(encoding="utf-8")

    assert "version: 12.0.2" in profile
    assert "source.source_class` literal" in prompt
    assert "`CURRICULUM_SCOPE` target" in prompt
    assert "`TEXTBOOK`으로 기록" in prompt
    assert '["PAST_EXAM", "TEXTBOOK"]' in prompt


def test_review_source_class_pack_keeps_reference_composition_prompt_contract() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.6"}}

    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
