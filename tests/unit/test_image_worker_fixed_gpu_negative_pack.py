from __future__ import annotations

import hashlib
from pathlib import Path

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.5"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.6"


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


def test_successor_uses_fixed_provider_negative_policy() -> None:
    compiled = compile_pack(SUCCESSOR)
    profile = next(item for item in compiled.profiles if item.profile.type == "image")
    rendered = (SUCCESSOR / profile.template).read_text(encoding="utf-8")

    assert profile.profile.version == "10.0.6"
    assert "HYBRID drawing의 `negative_prompt`는 `null`" in rendered
    assert "고정한 색·배경·글자·숫자·장식 금지 목록" in rendered
    assert "77토큰 안에서" in rendered
    assert "한국어 자유문으로 반복" in rendered
    assert "0부터 시작하는 배열 인덱스" in rendered


def test_successor_release_is_admitted_and_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())

    assert compiled.manifest.pack.version == "1.15.6"
    assert compiled.source_tree_sha256 == (
        "sha256:e6d0c58d5d7e673122b1d1e5daa2e8b3c6cd7f9d32c3a4ac8fa5f65b670f25d3"
    )
    assert built.bundle_sha256 == (
        "sha256:5d03d903313d582aeb15d6ed988b6a8f77246edde0d6519e24f87a5a0b2c5c13"
    )
    assert built.manifest_sha256 == (
        "sha256:f913661223e99b6522738f353f4c8a4a9aae16fc51b3aea7423b1f57523968ec"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.6", request
    )
