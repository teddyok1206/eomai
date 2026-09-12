from __future__ import annotations

import hashlib
from pathlib import Path

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.4"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.5"


def _workflow_request() -> WorkflowStartRequest:
    guidance = "IMAGE 시각자료를 정확히 1개 만들고 로컬 GPU로 흑백 합성한다."
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


def test_successor_defines_zero_based_visual_array_index() -> None:
    compiled = compile_pack(SUCCESSOR)
    profile = next(item for item in compiled.profiles if item.profile.type == "image")
    rendered = (SUCCESSOR / profile.template).read_text(encoding="utf-8")

    assert profile.profile.version == "10.0.5"
    assert "0부터 시작하는 배열 인덱스" in rendered
    assert "첫 `visuals` 원소의 값은 반드시 `0`" in rendered
    assert "IMAGE 앞에 TABLE이 있으면" in rendered
    assert "IMAGE 개수나" in rendered


def test_successor_release_is_admitted_and_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())

    assert compiled.manifest.pack.version == "1.15.5"
    assert compiled.source_tree_sha256 == (
        "sha256:fe0202fc3dec6fa790f3ec6e6f78b41fb5b83385a0240e1dbf77158c34152c97"
    )
    assert built.bundle_sha256 == (
        "sha256:cab2390d5e3c80ebddfecd86e5cbeaeb595b2e2f8593afef63c050a2953c0d31"
    )
    assert built.manifest_sha256 == (
        "sha256:8a7af17e3b19b6e43d7d34fd37d403b9668e85477c8d689d17cd32acd6e14e76"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.5", request
    )
