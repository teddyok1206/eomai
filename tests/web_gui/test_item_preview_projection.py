from __future__ import annotations

from typing import Any

import pytest
from eom_web_gui.item_preview_projection import (
    project_item_content,
    resolve_content_capability,
)

ITEM_ID = "item_" + "1" * 32
REVISION_ID = "itemrev_" + "2" * 32


def _artifact(schema_ref: str, media_type: str, ordinal: int) -> dict[str, object]:
    artifact_id = "artifact_" + f"{ordinal + 1:x}" * 32
    revision_id = "rev_" + f"{ordinal + 4:x}" * 32
    return {
        "artifact_id": artifact_id,
        "artifact_revision_id": revision_id,
        "artifact_member": None,
        "sha256": "sha256:" + f"{ordinal + 7:x}" * 64,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "logical_uri": f"nas://artifacts/{artifact_id}/{revision_id}",
    }


def _content_component(schema_ref: str = "eom.assessment.item-content/3.0") -> dict[str, object]:
    return {
        "item_component_id": "itemcomponent_" + "3" * 32,
        "item_revision_id": REVISION_ID,
        "component_type": "ITEM_CONTENT",
        "ordinal": 0,
        "logical_name": "assessment-item-content.json",
        "required": True,
        "artifact": _artifact(schema_ref, "application/json", 0),
    }


def _image_component(ordinal: int) -> dict[str, object]:
    return {
        "item_component_id": "itemcomponent_" + f"{ordinal + 4:x}" * 32,
        "item_revision_id": REVISION_ID,
        "component_type": "IMAGE",
        "ordinal": ordinal,
        "logical_name": f"content-team-visual-{ordinal}.png",
        "required": True,
        "artifact": _artifact(
            "eom://schemas/generated-item/stimulus-png/3.0", "image/png", ordinal + 1
        ),
    }


def _table(label: str = "") -> dict[str, object]:
    return {
        "kind": "TABLE",
        "label": label,
        "headers": ["구분", "값"],
        "rows": [["A", "1"]],
        "alignments": ["center", "right"],
    }


def _image(label: str = "") -> dict[str, object]:
    return {"kind": "IMAGE", "label": label}


def _content(*, visuals: list[dict[str, object]], visual_layout: str) -> dict[str, Any]:
    return {
        "schema_version": "3.0",
        "renderer_profile": "content-team-hwp-question-editor-v1",
        "authoring_prompt_sha256": "sha256:" + "a" * 64,
        "handoff_archive_sha256": "sha256:" + "b" * 64,
        "item_number": 7,
        "score_display": "2.5",
        "stem": "다음 자료를 해석하시오.",
        "bottom_stem": "옳은 것을 고르시오.",
        "inquiry": None,
        "labeled_blocks": [{"kind": "DATA", "content": "관측 자료이다."}],
        "visuals": visuals,
        "visual_layout": visual_layout,
        "statements": [],
        "choices": [
            {"number": label, "text": f"선택지 {index}"}
            for index, label in enumerate(("①", "②", "③", "④", "⑤"), start=1)
        ],
        "answer": {
            "answer_kind": "DIRECT_CHOICE",
            "number": "①",
            "answer_content": "선택지 1",
            "raw_line": "정답 : ① (선택지 1)",
            "statement_labels": [],
        },
        "explanations": {
            "authoring_intent": "자료 해석 능력을 평가한다.",
            "concept_source": "통합과학 자료 해석",
            "correct_answer": "자료에서 A의 값은 1이다.",
            "wrong_answer": "나머지는 자료와 다르다.",
        },
        "equation_sources": [],
    }


@pytest.mark.parametrize(
    ("visuals", "layout", "image_ordinals", "block_types", "captions"),
    (
        (
            [],
            "NONE",
            (),
            ("paragraph", "labeled_text", "paragraph"),
            (),
        ),
        (
            [_table()],
            "TABLE_ONLY",
            (),
            ("paragraph", "labeled_text", "table", "paragraph"),
            (None,),
        ),
        (
            [_image()],
            "IMAGE_ONLY",
            (0,),
            ("paragraph", "labeled_text", "image", "paragraph"),
            ("",),
        ),
        (
            [_image("(가)"), _image("(나)")],
            "IMAGE_IMAGE",
            (0, 1),
            ("paragraph", "labeled_text", "image", "image", "paragraph"),
            ("(가)", "(나)"),
        ),
        (
            [_image(), _table()],
            "IMAGE_TABLE",
            (0,),
            ("paragraph", "labeled_text", "image", "table", "paragraph"),
            ("", None),
        ),
        (
            [_table(), _image()],
            "TABLE_IMAGE",
            (1,),
            ("paragraph", "labeled_text", "table", "image", "paragraph"),
            (None, ""),
        ),
        (
            [_table("(가)"), _table("(나)")],
            "TABLE_TABLE",
            (),
            ("paragraph", "labeled_text", "table", "table", "paragraph"),
            ("(가)", "(나)"),
        ),
    ),
)
def test_content_team_projection_preserves_table_and_image_slot_shapes(
    visuals: list[dict[str, object]],
    layout: str,
    image_ordinals: tuple[int, ...],
    block_types: tuple[str, ...],
    captions: tuple[str | None, ...],
) -> None:
    components = [_content_component(), *(_image_component(value) for value in image_ordinals)]
    capability = resolve_content_capability(components, REVISION_ID)
    projected = project_item_content(
        content=_content(visuals=visuals, visual_layout=layout),
        capability=capability,
        components=components,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
    )

    assert tuple(block.type for block in projected.blocks) == block_types
    observed = tuple(
        getattr(block, "label", getattr(block, "caption", None))
        for block in projected.blocks
        if block.type in {"table", "image"}
    )
    assert observed == captions


def test_table_only_projection_never_requires_or_invents_an_image() -> None:
    components = [_content_component()]
    projected = project_item_content(
        content=_content(visuals=[_table()], visual_layout="TABLE_ONLY"),
        capability=resolve_content_capability(components, REVISION_ID),
        components=components,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
    )

    assert all(block.type != "image" for block in projected.blocks)


def test_inquiry_projection_is_native_content_without_image_placeholder() -> None:
    components = [_content_component()]
    content = _content(visuals=[], visual_layout="INQUIRY_BOX")
    content["inquiry"] = {
        "kind": "탐구",
        "goal": None,
        "procedure": "두 조건에서 값을 측정한다.",
        "result": "조건 A의 값이 더 컸다.",
    }

    projected = project_item_content(
        content=content,
        capability=resolve_content_capability(components, REVISION_ID),
        components=components,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
    )

    assert tuple(block.type for block in projected.blocks) == (
        "paragraph",
        "labeled_text",
        "inquiry",
        "paragraph",
    )
    assert all(block.type != "image" for block in projected.blocks)


def test_preview_preserves_blank_cells_used_by_canonical_exam_tables() -> None:
    components = [_content_component()]
    visual = _table()
    visual["headers"] = ["", "값"]
    visual["rows"] = [["A", ""]]

    projected = project_item_content(
        content=_content(visuals=[visual], visual_layout="TABLE_ONLY"),
        capability=resolve_content_capability(components, REVISION_ID),
        components=components,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
    )

    table = next(block for block in projected.blocks if block.type == "table")
    assert table.headers == ("", "값")
    assert table.rows == (("A", ""),)


def test_content_team_statement_ids_are_valid_stable_presentation_ids() -> None:
    components = [_content_component()]
    content = _content(visuals=[], visual_layout="NONE")
    content["statements"] = [
        {"label": "ㄱ", "text": "첫 번째 진술"},
        {"label": "ㄴ", "text": "두 번째 진술"},
        {"label": "ㄷ", "text": "세 번째 진술"},
    ]
    assert isinstance(content["explanations"], dict)
    content["explanations"]["correct_answer"] = "ㄱ. 옳다.\nㄴ. 옳다.\nㄷ. 옳다."

    projected = project_item_content(
        content=content,
        capability=resolve_content_capability(components, REVISION_ID),
        components=components,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
    )

    statement_set = next(block for block in projected.blocks if block.type == "statement_set")
    assert tuple(value.statement_id for value in statement_set.statements) == (
        "statement_s1",
        "statement_s2",
        "statement_s3",
    )


@pytest.mark.parametrize(
    "defect", ("missing", "extra", "wrong_hash", "wrong_revision", "wrong_uri")
)
def test_content_team_projection_rejects_dangling_or_mismatched_image_components(
    defect: str,
) -> None:
    components = [_content_component()]
    visuals = [_image()]
    if defect != "missing":
        image = _image_component(0 if defect != "extra" else 1)
        if defect == "wrong_hash":
            assert isinstance(image["artifact"], dict)
            image["artifact"]["sha256"] = "not-a-hash"
        if defect == "wrong_revision":
            image["item_revision_id"] = "itemrev_" + "f" * 32
        if defect == "wrong_uri":
            assert isinstance(image["artifact"], dict)
            image["artifact"]["logical_uri"] = "nas://artifacts/artifact_wrong/rev_wrong"
        components.append(image)
    with pytest.raises(ValueError):
        project_item_content(
            content=_content(visuals=visuals, visual_layout="IMAGE_ONLY"),
            capability=resolve_content_capability(components, REVISION_ID),
            components=components,
            item_id=ITEM_ID,
            item_revision_id=REVISION_ID,
        )


def test_content_capability_rejects_artifact_uri_that_differs_from_pinned_identity() -> None:
    component = _content_component()
    assert isinstance(component["artifact"], dict)
    component["artifact"]["logical_uri"] = "nas://artifacts/artifact_wrong/rev_wrong"

    with pytest.raises(ValueError, match="URI differs"):
        resolve_content_capability([component], REVISION_ID)


def test_unknown_content_schema_is_explicitly_unsupported() -> None:
    capability = resolve_content_capability(
        [_content_component("eom.assessment.item-content/99.0")], REVISION_ID
    )
    assert capability.profile is None
    assert capability.template_delivery_available is False


def test_content_schema_uri_alias_resolves_to_same_immutable_profile() -> None:
    capability = resolve_content_capability(
        [_content_component("eom://schemas/item-registry/assessment-item-content-v3")], REVISION_ID
    )
    assert capability.profile == "CONTENT_TEAM_V3"


def test_content_team_v2_uses_the_same_bounded_presentation_projection() -> None:
    components = [_content_component("eom.assessment.item-content/2.0")]
    content = _content(visuals=[_table()], visual_layout="TABLE_ONLY")
    content["schema_version"] = "2.0"
    capability = resolve_content_capability(components, REVISION_ID)

    projected = project_item_content(
        content=content,
        capability=capability,
        components=components,
        item_id=ITEM_ID,
        item_revision_id=REVISION_ID,
    )

    assert projected.profile == "CONTENT_TEAM_V2"
    assert tuple(block.type for block in projected.blocks) == (
        "paragraph",
        "labeled_text",
        "table",
        "paragraph",
    )
