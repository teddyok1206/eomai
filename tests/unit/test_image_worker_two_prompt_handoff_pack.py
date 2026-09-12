from __future__ import annotations

import hashlib
from pathlib import Path

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.8"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.9"


def _workflow_request() -> WorkflowStartRequest:
    guidance = "IMAGE 시각자료 하나를 사용해 통합과학 문항을 제작한다."
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
                "topic": "운동과 에너지",
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


def test_successor_changes_only_pack_image_profile_and_image_prompt() -> None:
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


def test_image_prompt_reads_both_team_lead_sources_and_preserves_hwpx_ownership() -> None:
    compiled = compile_pack(SUCCESSOR)
    image_profile = next(
        profile for profile in compiled.profiles if profile.profile.type == "image"
    )
    prompt = (SUCCESSOR / image_profile.template).read_text(encoding="utf-8")

    assert image_profile.profile.version == "10.0.7"
    ordered_sources = (
        "content-team-integrated-science-authoring-v05.md",
        "content-team-hwp-question-editor-handoff-v1.md",
        "kice-integrated-science-illustration-v1.md",
    )
    positions = tuple(prompt.index(source) for source in ordered_sources)
    assert positions == tuple(sorted(positions))
    for required in (
        "IMAGE가 하나이면 하나의 PNG만 만들고 drawing label은 빈 문자열",
        "IMAGE가 둘이면 visual ordinal 0과 1에 서로 다른 PNG",
        "별도 편집 가능한 텍스트 행",
        "PNG의 픽셀, SVG overlay 또는 GPU 배경에도 넣지 마라",
        "IMAGE와 TABLE이 섞이면 실제 배열 ordinal",
        "deterministic SVG overlay",
    ):
        assert required in prompt


def test_successor_release_is_admitted_and_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())

    assert compiled.manifest.pack.version == "1.15.9"
    assert compiled.source_tree_sha256 == (
        "sha256:bb309a4542b87d94e9699a8fce3905c779e41f004df581c1343821e077d55ce7"
    )
    assert built.bundle_sha256 == (
        "sha256:b30fa548aba9ee0be8a83685036300a119c5bfc1d37faea69a6cb95d2b874190"
    )
    assert built.manifest_sha256 == (
        "sha256:8c6472689c359d5cf09be85bb093f25c8cede65fcb18b13aefafae32179d2bb7"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.9", request
    )
