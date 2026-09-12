from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_content_pack import render_prompt
from eom_identifiers import sha256_file

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.6"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.7"


def _workflow_request() -> WorkflowStartRequest:
    guidance = (
        "포물선 운동의 장면 설정과 수치를 자료에 제시하고, 운동 경로를 나타낸 "
        "흑백 IMAGE 시각자료가 포함된 ㄱㄴㄷ 문항을 작성한다."
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
                "topic": "포물선 운동",
                "task_type": "IMAGE",
                "difficulty": "MEDIUM",
                "authoring_guidance": guidance,
                "authoring_guidance_sha256": (
                    "sha256:" + hashlib.sha256(guidance.encode()).hexdigest()
                ),
                "curriculum_selected_unit_key": "eom.is.middle.1-1",
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


def _profile(pack_type: str) -> Any:
    compiled = compile_pack(SUCCESSOR)
    return next(profile for profile in compiled.profiles if profile.profile.type == pack_type)


def test_successor_is_complete_and_changes_only_required_image_contract_resources() -> None:
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
        "profiles/generated-knowledge-authoring.yaml",
        "profiles/generated-knowledge-review.yaml",
        "prompt-templates/authoring.md",
        "prompt-templates/review.md",
    }
    assert successor["prompt-templates/image.md"] == predecessor["prompt-templates/image.md"]


def test_two_authoritative_team_lead_guidance_files_remain_byte_frozen() -> None:
    assert (
        sha256_file(
            ROOT / "config/control-plane/standard-item-v5/references/guidance/"
            "content-team-integrated-science-authoring-v05.md"
        )
        == "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    )
    assert (
        sha256_file(
            ROOT / "config/control-plane/standard-item-v6/references/guidance/"
            "content-team-hwp-question-editor-handoff-v1.md"
        )
        == "sha256:6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5"
    )


def test_authoring_and_review_render_authoritative_required_image_invariant() -> None:
    request = _workflow_request()
    assert request.item_brief is not None
    reviewed = request.item_brief.model_dump(mode="json") | {
        "knowledge_source_mode": "graph_grounded"
    }
    base_context = {
        "workflow": {"id": "workflow_" + "1" * 32, "step_key": "authoring"},
        "request": {"image_mode": "required"},
        "brief": {
            "reviewed_item_brief_json": json.dumps(
                reviewed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        },
        "pack": {"release_id": "packrel_" + "2" * 32},
    }
    authoring_profile = _profile("authoring")
    authoring = render_prompt(
        (SUCCESSOR / authoring_profile.template).read_text(encoding="utf-8"),
        base_context,
        authoring_profile.required_context,
    ).text
    review_profile = _profile("review")
    review = render_prompt(
        (SUCCESSOR / review_profile.template).read_text(encoding="utf-8"),
        {
            **base_context,
            "workflow": {"id": "workflow_" + "1" * 32, "step_key": "review"},
            "upstream": {
                "authoring": {
                    "result_json": "{}",
                    "artifact_id": "artifact_" + "3" * 32,
                    "artifact_revision_id": "rev_" + "4" * 32,
                    "sha256": "sha256:" + "5" * 64,
                }
            },
        },
        review_profile.required_context,
    ).text

    assert authoring_profile.profile.version == "10.0.2"
    assert review_profile.profile.version == "10.0.2"
    for rendered in (authoring, review):
        assert "AUTHORITATIVE_IMAGE_MODE: required" in rendered
        assert "mock_exam_slot" in rendered
        assert "DATA" in rendered and "CONDITION" in rendered
        assert "/visuals/0/kind" in rendered
        assert "/labeled_blocks/0/content" in rendered
        assert "PAST_EXAM" in rendered and "STRUCTURE_PATTERN" in rendered
    assert "적어도 하나 만든다" in authoring
    assert "REQUIRED_IMAGE_MISSING" in review
    assert "CONDITION_MISUSED_AS_DATA" in review


def test_successor_release_is_admitted_and_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)
    request = _workflow_request_from_api(_workflow_request())

    assert compiled.manifest.pack.version == "1.15.7"
    assert compiled.source_tree_sha256 == (
        "sha256:a13196a424be264a6090b1cb2a00bb37ee40c610e3ae72891b46b319d31c2234"
    )
    assert built.bundle_sha256 == (
        "sha256:c99c311c8ee770e91015e06f4f582b2a4c25ad4ae455044f43e3289e6252e892"
    )
    assert built.manifest_sha256 == (
        "sha256:916d6d3a5462c1eecdbce5e24e4317c8d0892c5c0cc8ec9363fefb1db3af001a"
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.15.7", request
    )
