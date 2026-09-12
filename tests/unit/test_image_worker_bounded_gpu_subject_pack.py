from __future__ import annotations

import hashlib
from pathlib import Path

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.3"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.4"


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


def test_successor_explains_exact_provenance_and_bounded_gpu_projection() -> None:
    compiled = compile_pack(SUCCESSOR)
    profile = next(item for item in compiled.profiles if item.profile.type == "image")
    rendered = (SUCCESSOR / profile.template).read_text(encoding="utf-8")

    assert profile.profile.version == "10.0.4"
    assert "`drawing.generation_prompt`" in rendered
    assert "`illustration_prompt`를 바이트 단위로 정확히 복사" in rendered
    assert "`drawing.alt_text`를 GPU의 짧은 의미 주제로 사용" in rendered
    assert "50 Unicode 문자 이하" in rendered
    assert "120 Unicode 문자 이하" in rendered
    assert "scene_description, scientific_constraints" in rendered


def test_successor_release_is_admitted_and_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())

    assert compiled.manifest.pack.version == "1.15.4"
    assert compiled.source_tree_sha256 == (
        "sha256:26e2ee56a6b517ba5bcb7f4b1f46c825ec1fe600f9d462666b83206c6f87cc5d"
    )
    assert built.bundle_sha256 == (
        "sha256:aafb2d7ce6e89b04e56815a5a3ac4476fd23099d073bc1620998273b49545a3a"
    )
    assert built.manifest_sha256 == (
        "sha256:89d4c46a01a7ae4eedbd11efead14c8e2362ab622a6efd36c5c4d4ec15312a69"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.4", request
    )
