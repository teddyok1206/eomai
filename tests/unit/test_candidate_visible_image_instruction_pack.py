from __future__ import annotations

import json
from pathlib import Path

from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_content_pack import render_prompt
from eom_identifiers import sha256_file

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.7"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.15.8"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _profile(pack_type: str):  # type: ignore[no-untyped-def]
    compiled = compile_pack(SUCCESSOR)
    return next(profile for profile in compiled.profiles if profile.profile.type == pack_type)


def test_successor_changes_only_candidate_instruction_boundary_resources() -> None:
    predecessor = _files(PREDECESSOR)
    successor = _files(SUCCESSOR)

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


def test_authoring_and_review_prompts_distinguish_candidate_facts_from_image_work() -> None:
    reviewed_brief = {
        "schema_version": "3.0",
        "subject": "통합과학",
        "topic": "포물선 운동",
        "task_type": "IMAGE",
        "difficulty": "MEDIUM",
        "authoring_guidance": "자료와 그림을 해석하는 문항을 작성한다.",
        "authoring_guidance_sha256": "sha256:" + "1" * 64,
        "curriculum_selected_unit_key": "eom.is.middle.1-1",
        "original_request_sha256": "2" * 64,
        "knowledge_source_mode": "graph_grounded",
    }
    base_context = {
        "workflow": {"id": "workflow_" + "3" * 32, "step_key": "authoring"},
        "request": {"image_mode": "required"},
        "brief": {
            "reviewed_item_brief_json": json.dumps(
                reviewed_brief, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        },
        "pack": {"release_id": "packrel_" + "4" * 32},
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
            "workflow": {"id": "workflow_" + "3" * 32, "step_key": "review"},
            "upstream": {
                "authoring": {
                    "result_json": "{}",
                    "artifact_id": "artifact_" + "5" * 32,
                    "artifact_revision_id": "rev_" + "6" * 32,
                    "sha256": "sha256:" + "7" * 64,
                }
            },
        },
        review_profile.required_context,
    ).text

    assert authoring_profile.profile.version == "10.0.3"
    assert review_profile.profile.version == "10.0.3"
    for rendered in (authoring, review):
        assert "학생 공개" in rendered
        assert "그림의 P와 Q는 각각 t=1 s와 t=2 s인 공의 위치이다" in rendered
        assert "illustration_prompt" in rendered
        assert "scientific_constraints" in rendered
    assert "그림에는 P와 Q를 표시한다" in authoring
    assert "그림에는 … 표시한다" in review
    assert "ordered `visuals`에는 IMAGE 슬롯만" in authoring
    assert "CANDIDATE_VISIBLE_IMAGE_INSTRUCTION" in review


def test_successor_hashes_are_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(SUCCESSOR)
    built = build_pack(SUCCESSOR, tmp_path)

    assert compiled.manifest.pack.version == "1.15.8"
    assert compiled.source_tree_sha256 == (
        "sha256:e48ecf893dc0319c149a1be4db6483c63a02d6f0f9a7b3d44069750af58a260e"
    )
    assert built.bundle_sha256 == (
        "sha256:fdb88f88ed18205d6151e64898ccaf16d1c3990e35458cddebfba1964a84ec75"
    )
    assert built.manifest_sha256 == (
        "sha256:e4736837685103f8c267c9e594262cc18caeda7c4ab572efd0f6f8f7164afcdd"
    )
