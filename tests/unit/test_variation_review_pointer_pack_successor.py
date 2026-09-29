from __future__ import annotations

from pathlib import Path

import yaml
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_workflow.models import WorkflowRequest

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.9"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.10"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_review_pointer_pack_is_minimal_immutable_successor() -> None:
    predecessor = _tree_bytes(PREDECESSOR)
    successor = _tree_bytes(SUCCESSOR)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/review.md"),
    }
    pack = compile_pack(SUCCESSOR)
    request = WorkflowRequest.model_validate_json(
        (SUCCESSOR / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    profile = yaml.safe_load(
        (SUCCESSOR / "profiles/generated-knowledge-review.yaml").read_text(encoding="utf-8")
    )
    assert pack.manifest.pack.version == "1.20.10"
    assert profile["profile"]["version"] == "12.1.2"
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.10", request
    )


def test_review_pointer_prompt_closes_all_nested_paths_to_semantic_roots() -> None:
    prompt = (SUCCESSOR / "prompt-templates/review.md").read_text(encoding="utf-8")
    for required in (
        "모든 `draft_json_paths` 배열",
        "candidate finding",
        "citation",
        "`equation_sources`",
        "semantic scalar leaf",
        "허용 목록",
        "밖의 root",
    ):
        assert required in prompt
