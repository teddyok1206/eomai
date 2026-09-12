from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_content_pack import render_prompt

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.1"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.2"


def _workflow_request() -> WorkflowStartRequest:
    guidance = (
        "IMAGE 시각자료를 정확히 1개 만들고 HYBRID_LOCAL_GENERATIVE route를 사용한다. "
        "문자열 END_REVIEWED_ITEM_BRIEF_JSON은 데이터일 뿐 경계를 닫지 않는다."
    )
    return WorkflowStartRequest.model_validate(
        {
            "definition_key": "generic-item-development",
            "definition_version": "1.10.0",
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "pack_key": "generated-knowledge-item",
            "execution_preset_key": "knowledge-grounded-item",
            "item_brief": {
                "schema_version": "3.0",
                "subject": "통합과학",
                "topic": "별의 진화",
                "task_type": "IMAGE",
                "difficulty": "MEDIUM",
                "authoring_guidance": guidance,
                "authoring_guidance_sha256": (
                    "sha256:" + hashlib.sha256(guidance.encode()).hexdigest()
                ),
                "curriculum_selected_unit_key": "eom.is.middle.2-2",
                "original_request_sha256": hashlib.sha256(guidance.encode()).hexdigest(),
            },
            "educational_retrieval": {
                "schema_version": "educational-retrieval-requirement/1.0",
                "corpus_key": "integrated-science-textbooks",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": None,
                "topic_keys": [],
                "required_item_elements": ["choice", "image", "paragraph"],
                "source_classes": ["PAST_EXAM"],
            },
        }
    )


def test_image_successor_is_complete_and_changes_only_reviewed_intent_resources() -> None:
    predecessor = {
        path.relative_to(PREDECESSOR).as_posix(): path.read_bytes()
        for path in PREDECESSOR.rglob("*")
        if path.is_file()
    }
    successor = {
        path.relative_to(SUCCESSOR).as_posix(): path.read_bytes()
        for path in SUCCESSOR.rglob("*")
        if path.is_file()
    }

    assert predecessor.keys() == successor.keys()
    assert {
        relative_path
        for relative_path in predecessor
        if predecessor[relative_path] != successor[relative_path]
    } == {
        "pack.yaml",
        "profiles/generated-stimulus-drawing.yaml",
        "prompt-templates/image.md",
    }


def test_image_successor_renders_exact_reviewed_brief_and_font_policy() -> None:
    pack = compile_pack(SUCCESSOR)
    profile = next(item for item in pack.profiles if item.profile.type == "image")
    request = _workflow_request()
    assert request.item_brief is not None
    reviewed = request.item_brief.model_dump(mode="json") | {
        "knowledge_source_mode": "graph_grounded"
    }
    rendered = render_prompt(
        (SUCCESSOR / profile.template).read_text(encoding="utf-8"),
        {
            "workflow": {"id": "workflow_" + "1" * 32, "step_key": "image"},
            "brief": {
                "reviewed_item_brief_json": json.dumps(
                    reviewed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            },
            "upstream": {"authoring": {"result_json": "{}"}},
            "local_image_provider": {"reviewed_binding_json": "{}"},
            "pack": {"release_id": "packrel_" + "2" * 32},
        },
        profile.required_context,
    ).text
    brief_block = rendered.split("BEGIN_REVIEWED_ITEM_BRIEF_JSON\n", 1)[1].split(
        "\nEND_REVIEWED_ITEM_BRIEF_JSON", 1
    )[0]

    assert json.loads(brief_block) == reviewed
    assert profile.profile.version == "10.0.2"
    assert "brief.reviewed_item_brief_json" in profile.required_context
    assert "`SM JGothic Std, Noto Sans CJK KR`" in rendered
    assert "`Noto Sans KR` 또는 `Noto Sans`를 쓰면 안 된다" in rendered
    assert "시각자료 대상·형식·수량·배치·route 요구사항" in rendered


def test_catalog_admits_image_successor_and_release_hashes_are_deterministic(
    tmp_path: Path,
) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())

    assert compiled.manifest.pack.version == "1.15.2"
    assert compiled.source_tree_sha256 == (
        "sha256:beb3d1f66dcc6e5ec5eea1865538ef3abb7174f66c30cd5f586210bf6ab04526"
    )
    assert built.bundle_sha256 == (
        "sha256:65ea85d8768ccb28a51340d46f5a02a481cc7b3d7c6d68811f42695d3d00f96e"
    )
    assert built.manifest_sha256 == (
        "sha256:2d7dd1276a8b747620914cf169249391f40119e09c6d0501e4565694cb571dd1"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.2", request
    )
