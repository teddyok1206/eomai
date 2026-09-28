from __future__ import annotations

import hashlib
from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.local_image_prompt_policy import (
    LOCAL_GPU_MINIMAL_NEGATIVE_REQUIREMENTS,
    LOCAL_GPU_MINIMAL_PROMPT_POLICY_REVISION,
    LOCAL_GPU_MINIMAL_STYLE_PREFIX,
    compose_local_gpu_prompt_plan,
)
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _local_image_prompt_contract,
)
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.0"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.1"


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_minimal_line_art_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)

    assert predecessor.source_tree_sha256 == (
        "sha256:2f2083ea3b3ed9535c0f346b913f8eb91f9283db0c40a3c95c1846266e55d0d3"
    )
    assert pack.manifest.pack.version == "1.20.1"
    assert pack.manifest.compatibility.protocol.minimum == "1.24.0"
    assert pack.manifest.compatibility.protocol.maximum_exclusive == "1.25.0"
    assert pack.manifest.compatibility.workflow_definitions[0].versions == ("1.13.0",)
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item",
        "1.20.1",
        request,
    )


def test_successor_changes_only_pack_image_profile_and_derived_image_prompt() -> None:
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
        "대상 개수, 실루엣, 자세, 시점, 상대 위치, 겹침",
        "촘촘한 해칭",
        "큰 외곽선과 식별에 필요한 큰",
        "내부 윤곽선만 남기고",
        "액면 높이·연결관·가열 위치·힘의 방향",
        "`DETERMINISTIC_SVG`",
    ):
        assert requirement in prompt
    for relative_path, expected in (
        (
            "config/control-plane/standard-item-v5/references/guidance/"
            "content-team-integrated-science-authoring-v05.md",
            "62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435",
        ),
        (
            "config/control-plane/standard-item-v6/references/guidance/"
            "content-team-hwp-question-editor-handoff-v1.md",
            "6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5",
        ),
    ):
        assert hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected


def test_pack_selects_minimal_prompt_policy_without_changing_worker_subject() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.1"}}
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_MINIMAL_LINE_ART_V2"

    subject = "one compact automobile in side view isolated on white"
    plan = compose_local_gpu_prompt_plan(
        subject=subject,
        production_route="HYBRID_LOCAL_GENERATIVE",
        prompt_contract="ASSESSMENT_MINIMAL_LINE_ART_V2",
    )
    assert plan.policy_revision == LOCAL_GPU_MINIMAL_PROMPT_POLICY_REVISION
    assert plan.positive_prompt == f"{LOCAL_GPU_MINIMAL_STYLE_PREFIX} {subject}"
    assert plan.negative_prompt == ", ".join(LOCAL_GPU_MINIMAL_NEGATIVE_REQUIREMENTS)
    assert "hatching" not in plan.positive_prompt
    assert "microtexture" in plan.negative_prompt
    assert "changed viewpoint" in plan.negative_prompt
