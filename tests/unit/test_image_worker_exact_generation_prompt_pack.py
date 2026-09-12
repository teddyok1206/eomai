from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_workflow.models import ContentTeamIllustrationDrawingV8, GeneratedVectorDrawingV6
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.2"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.3"


def _workflow_request() -> WorkflowStartRequest:
    guidance = "IMAGE 시각자료를 정확히 1개 만들고 팀장 원문을 로컬 모델에 그대로 전달한다."
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


def _drawing(generation_prompt: str) -> ContentTeamIllustrationDrawingV8:
    illustration_prompt = (
        "아래의 요청사항에 대한 문제의 그림을 그려줘. "
        "내가 소스에 넣어둔 이미지 규칙을 잊지 말고 지켜 "
        "별의 진화를 흑백 자연 장면으로 표현한다."
    )
    return ContentTeamIllustrationDrawingV8.model_validate(
        {
            "visual_ordinal": 0,
            "label": "",
            "illustration_prompt": illustration_prompt,
            "drawing": {
                "kind": "natural_scene",
                "background_style": "WHITE",
                "alt_text": "별의 진화 단계 삽화",
                "scene_description": "별의 진화 단계를 흑백으로 표현한다.",
                "scientific_constraints": ["정답을 암시하는 문자를 넣지 않는다."],
                "production_route": "HYBRID_LOCAL_GENERATIVE",
                "route_reason": "REALISTIC_NATURAL_SCENE_REQUIRED",
                "generation_prompt": generation_prompt,
                "negative_prompt": "color, answer-bearing text",
                "width_px": 800,
                "height_px": 500,
                "svg_overlay": (
                    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
                    'viewBox="0 0 800 500"><rect x="0" y="0" width="800" height="500" '
                    'fill="white" stroke="black"/></svg>'
                ),
                "required_labels": [],
            },
        }
    )


def test_successor_changes_only_pack_profile_and_image_prompt() -> None:
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


def test_successor_requires_exact_content_team_prompt_copy() -> None:
    prompt = (
        "아래의 요청사항에 대한 문제의 그림을 그려줘. "
        "내가 소스에 넣어둔 이미지 규칙을 잊지 말고 지켜 "
        "별의 진화를 흑백 자연 장면으로 표현한다."
    )
    valid = _drawing(prompt)
    assert isinstance(valid.drawing, GeneratedVectorDrawingV6)
    assert valid.drawing.generation_prompt == prompt
    with pytest.raises(ValidationError, match="hybrid generation prompt differs"):
        _drawing(prompt + " 추가 설명")


def test_successor_prompt_exposes_the_semantic_equality_rule() -> None:
    compiled = compile_pack(SUCCESSOR)
    profile = next(item for item in compiled.profiles if item.profile.type == "image")
    rendered = (SUCCESSOR / profile.template).read_text(encoding="utf-8")
    assert profile.profile.version == "10.0.3"
    assert "`drawing.generation_prompt`" in rendered
    assert "`illustration_prompt`를 바이트 단위로 정확히 복사" in rendered
    assert "번역, 요약, 재작성, 순서 변경, 접두사" in rendered


def test_successor_release_is_admitted_and_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())
    assert compiled.manifest.pack.version == "1.15.3"
    assert compiled.source_tree_sha256 == (
        "sha256:66d4b425cb039207066c34a997c010fbff46920c06925359914aa37651940200"
    )
    assert built.bundle_sha256 == (
        "sha256:2ab6e6e87afc8804b63852e715c23f57f6590b3370cb4cd51c5df0cd8089bd00"
    )
    assert built.manifest_sha256 == (
        "sha256:0671b790574f13e7a78472c5d118705e0696c7a9fef0e86ff630651b0b71ec01"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.3", request
    )
