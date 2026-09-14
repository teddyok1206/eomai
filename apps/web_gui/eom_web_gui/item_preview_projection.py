"""Fail-closed projection of canonical Item content into the browser preview contract.

The Application API is authoritative for typed content.  This module treats its HTTP response as
untrusted input, preserves ordered content, and maps component pointers in O(component count).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from eom_web_gui.contracts import (
    PreviewBlockV3,
    PreviewChoice,
    PreviewEquationBlock,
    PreviewImageBlockV3,
    PreviewInquiryBlock,
    PreviewLabeledTextBlock,
    PreviewParagraphBlockV3,
    PreviewStatement,
    PreviewStatementExplanation,
    PreviewStatementSetBlock,
    PreviewTableBlockV3,
)

ContentProfile = Literal["BLOCKS_V1", "CONTENT_TEAM_V2", "CONTENT_TEAM_V3"]

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9_]{7,127}$")
_CONTENT_PROFILE_BY_SCHEMA: dict[str, ContentProfile] = {
    "eom.assessment.item-content/1.0": "BLOCKS_V1",
    "eom://schemas/item-registry/assessment-item-content-v1": "BLOCKS_V1",
    "eom.assessment.item-content/2.0": "CONTENT_TEAM_V2",
    "eom://schemas/item-registry/assessment-item-content-v2": "CONTENT_TEAM_V2",
    "eom.assessment.item-content/3.0": "CONTENT_TEAM_V3",
    "eom://schemas/item-registry/assessment-item-content-v3": "CONTENT_TEAM_V3",
}
_EXPECTED_CONTENT_VERSION: dict[ContentProfile, str] = {
    "BLOCKS_V1": "1.0",
    "CONTENT_TEAM_V2": "2.0",
    "CONTENT_TEAM_V3": "3.0",
}
_CHOICE_LABELS = ("①", "②", "③", "④", "⑤")


@dataclass(frozen=True)
class ContentCapability:
    schema_ref: str
    profile: ContentProfile | None
    template_delivery_available: bool


@dataclass(frozen=True)
class ProjectedItemContent:
    profile: ContentProfile
    locale: str
    title: str | None
    item_number: int | None
    score_display: str
    blocks: tuple[PreviewBlockV3, ...]
    choices: tuple[PreviewChoice, ...]
    answer: str
    explanation: str
    concept_source: str | None
    authoring_intent: str | None
    statement_explanations: tuple[PreviewStatementExplanation, ...]


def resolve_content_capability(
    components: list[dict[str, Any]], item_revision_id: str
) -> ContentCapability:
    """Resolve one canonical content component and reject duplicate or dangling pointers."""

    keyed: dict[tuple[str, int], dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict) or component.get("item_revision_id") != item_revision_id:
            raise ValueError("Item component points at another revision")
        component_type = component.get("component_type")
        ordinal = component.get("ordinal")
        if not isinstance(component_type, str) or not isinstance(ordinal, int):
            raise ValueError("Item component key is invalid")
        key = (component_type, ordinal)
        if key in keyed:
            raise ValueError("Item component key is duplicated")
        keyed[key] = component
    content = keyed.get(("ITEM_CONTENT", 0))
    if content is None or content.get("required") is not True:
        raise ValueError("Canonical Item content component is missing")
    artifact = _artifact_pointer(content)
    if content.get("logical_name") != "assessment-item-content.json":
        raise ValueError("Canonical Item content logical name is invalid")
    if artifact.get("media_type") != "application/json":
        raise ValueError("Canonical Item content media type is invalid")
    schema_ref = _required_text(artifact, "schema_ref", maximum=256)
    return ContentCapability(
        schema_ref=schema_ref,
        profile=_CONTENT_PROFILE_BY_SCHEMA.get(schema_ref),
        template_delivery_available=schema_ref in _CONTENT_PROFILE_BY_SCHEMA,
    )


def project_item_content(
    *,
    content: dict[str, Any],
    capability: ContentCapability,
    components: list[dict[str, Any]],
    item_id: str,
    item_revision_id: str,
) -> ProjectedItemContent:
    profile = capability.profile
    if profile is None:
        raise ValueError("Unsupported Item content cannot be projected")
    if content.get("schema_version") != _EXPECTED_CONTENT_VERSION[profile]:
        raise ValueError("Item content version differs from its component schema")
    if profile == "BLOCKS_V1":
        return _project_blocks_v1(content, item_id, item_revision_id)
    return _project_content_team(
        content,
        profile=profile,
        components=components,
        item_id=item_id,
        item_revision_id=item_revision_id,
    )


def _project_blocks_v1(
    content: dict[str, Any], item_id: str, item_revision_id: str
) -> ProjectedItemContent:
    body = _required_list(content, "body")
    blocks: list[PreviewBlockV3] = []
    for raw in body:
        block = _object(raw, "Item content block")
        block_type = block.get("type")
        if block_type == "paragraph":
            blocks.append(PreviewParagraphBlockV3.model_validate(block))
        elif block_type == "equation":
            blocks.append(PreviewEquationBlock.model_validate(block))
        elif block_type == "table":
            blocks.append(PreviewTableBlockV3.model_validate(block))
        elif block_type == "statement_set":
            blocks.append(PreviewStatementSetBlock.model_validate(block))
        elif block_type == "image":
            artifact = _object(block.get("artifact"), "Item image pointer")
            blocks.append(
                PreviewImageBlockV3.model_validate(
                    {
                        "block_id": block.get("block_id"),
                        "type": "image",
                        "purpose": block.get("purpose"),
                        "label": "",
                        "media_url": (
                            f"/studio/api/v1/items/{item_id}/revisions/"
                            f"{item_revision_id}/media/{block.get('block_id')}"
                        ),
                        "media_type": artifact.get("media_type"),
                        "sha256": artifact.get("sha256"),
                        "alt_text": block.get("alt_text"),
                        "width_px": block.get("width_px"),
                        "height_px": block.get("height_px"),
                    }
                )
            )
        else:
            raise ValueError("Item content block type is unsupported")
    interaction = _object(content.get("interaction"), "Item interaction")
    source_choices = _required_list(interaction, "choices")
    choices = tuple(
        PreviewChoice.model_validate(_object(value, "Item choice")) for value in source_choices
    )
    solution = _object(content.get("solution"), "Item solution")
    correct_ids = _required_list(solution, "correct_choice_ids")
    if len(correct_ids) != 1 or not isinstance(correct_ids[0], str):
        raise ValueError("Item solution must identify exactly one choice")
    answer = next((choice.label for choice in choices if choice.choice_id == correct_ids[0]), None)
    if answer is None:
        raise ValueError("Item solution points at an unknown choice")
    raw_explanations = _required_list(solution, "statement_explanations")
    explanations = tuple(
        PreviewStatementExplanation.model_validate(_object(value, "Statement explanation"))
        for value in raw_explanations
    )
    score = _object(content.get("score"), "Item score")
    points = score.get("points")
    if not isinstance(points, int) or isinstance(points, bool):
        raise ValueError("Item score is invalid")
    return ProjectedItemContent(
        profile="BLOCKS_V1",
        locale=_required_text(content, "locale", maximum=16),
        title=_required_text(content, "title", maximum=20_000),
        item_number=None,
        score_display=str(points),
        blocks=tuple(blocks),
        choices=choices,
        answer=answer,
        explanation=_required_text(solution, "explanation", maximum=48_000),
        concept_source=None,
        authoring_intent=_optional_text(solution, "authoring_intent", maximum=20_000),
        statement_explanations=explanations,
    )


def _project_content_team(
    content: dict[str, Any],
    *,
    profile: Literal["CONTENT_TEAM_V2", "CONTENT_TEAM_V3"],
    components: list[dict[str, Any]],
    item_id: str,
    item_revision_id: str,
) -> ProjectedItemContent:
    blocks: list[PreviewBlockV3] = [
        PreviewParagraphBlockV3(
            block_id="block_stem",
            purpose="stem",
            text=_required_text(content, "stem", maximum=24_000),
        )
    ]
    labeled = _required_list(content, "labeled_blocks")
    for index, raw in enumerate(labeled):
        value = _object(raw, "Labeled Item block")
        kind = value.get("kind")
        blocks.append(
            PreviewLabeledTextBlock.model_validate(
                {
                    "block_id": f"block_labeled_{index}",
                    "kind": kind,
                    "label": {"DATA": "<자료>", "CONDITION": "<조건>"}.get(str(kind)),
                    "text": value.get("content"),
                }
            )
        )
    inquiry = content.get("inquiry")
    visuals = _required_list(content, "visuals")
    if inquiry is not None:
        if visuals or content.get("visual_layout") != "INQUIRY_BOX":
            raise ValueError("Inquiry Item cannot contain general visual slots")
        if _image_components_by_visual_ordinal(components, item_revision_id):
            raise ValueError("Inquiry Item cannot contain image components")
        value = _object(inquiry, "Item inquiry")
        blocks.append(
            PreviewInquiryBlock.model_validate(
                {
                    "block_id": "block_inquiry",
                    "kind": value.get("kind"),
                    "goal": value.get("goal"),
                    "procedure": value.get("procedure"),
                    "result": value.get("result"),
                }
            )
        )
    else:
        image_components = _image_components_by_visual_ordinal(components, item_revision_id)
        expected_image_ordinals: set[int] = set()
        observed_visual_shape: list[tuple[str, str]] = []
        for ordinal, raw in enumerate(visuals):
            visual = _object(raw, "Item visual")
            kind = visual.get("kind")
            label = visual.get("label")
            if not isinstance(label, str):
                raise ValueError("Item visual label is invalid")
            observed_visual_shape.append((str(kind), label))
            if kind == "TABLE":
                blocks.append(
                    PreviewTableBlockV3.model_validate(
                        {
                            "block_id": f"block_visual_{ordinal}",
                            "purpose": "data",
                            "caption": label or None,
                            "headers": visual.get("headers"),
                            "rows": visual.get("rows"),
                        }
                    )
                )
            elif kind == "IMAGE":
                expected_image_ordinals.add(ordinal)
                component = image_components.get(ordinal)
                if component is None:
                    raise ValueError("Item image component is missing")
                artifact = _artifact_pointer(component)
                blocks.append(
                    PreviewImageBlockV3.model_validate(
                        {
                            "block_id": f"block_visual_{ordinal}",
                            "purpose": "stimulus",
                            "label": label,
                            "media_url": (
                                f"/studio/api/v1/items/{item_id}/revisions/"
                                f"{item_revision_id}/visuals/{ordinal}"
                            ),
                            "media_type": artifact.get("media_type"),
                            "sha256": artifact.get("sha256"),
                            "alt_text": (
                                f"문항 시각 자료 {label}"
                                if isinstance(label, str) and label
                                else "문항 시각 자료"
                            ),
                            "width_px": 800,
                            "height_px": 500,
                        }
                    )
                )
            else:
                raise ValueError("Item visual kind is unsupported")
        if set(image_components) != expected_image_ordinals:
            raise ValueError("Item image components differ from the canonical visual slots")
        expected_layout = {
            (): "NONE",
            (("IMAGE", ""),): "IMAGE_ONLY",
            (("TABLE", ""),): "TABLE_ONLY",
            (("IMAGE", ""), ("TABLE", "")): "IMAGE_TABLE",
            (("TABLE", ""), ("IMAGE", "")): "TABLE_IMAGE",
            (("IMAGE", "(가)"), ("IMAGE", "(나)")): "IMAGE_IMAGE",
            (("TABLE", "(가)"), ("TABLE", "(나)")): "TABLE_TABLE",
        }.get(tuple(observed_visual_shape))
        if expected_layout is None or content.get("visual_layout") != expected_layout:
            raise ValueError("Item visual slots differ from their canonical layout")
    blocks.append(
        PreviewParagraphBlockV3(
            block_id="block_bottom_stem",
            purpose="prompt",
            text=_required_text(content, "bottom_stem", maximum=4000),
        )
    )
    raw_statements = _required_list(content, "statements")
    statements = tuple(
        PreviewStatement(
            statement_id=f"statement_s{index + 1}",
            label=_required_text(_object(raw, "Item statement"), "label", maximum=16),
            text=_required_text(_object(raw, "Item statement"), "text", maximum=20_000),
        )
        for index, raw in enumerate(raw_statements)
    )
    if statements:
        blocks.append(
            PreviewStatementSetBlock(
                block_id="block_statements",
                statements=statements,
            )
        )
    raw_choices = _required_list(content, "choices")
    choices = tuple(
        PreviewChoice(
            choice_id=f"choice_{index + 1}",
            label=_required_text(_object(raw, "Item choice"), "number", maximum=16),
            text=_required_text(_object(raw, "Item choice"), "text", maximum=20_000),
        )
        for index, raw in enumerate(raw_choices)
    )
    if tuple(choice.label for choice in choices) != _CHOICE_LABELS:
        raise ValueError("Content-team Item choices are not in canonical order")
    answer = _object(content.get("answer"), "Item answer")
    answer_number = _required_text(answer, "number", maximum=16)
    explanations = _object(content.get("explanations"), "Item explanations")
    correct = _required_text(explanations, "correct_answer", maximum=24_000)
    wrong = _optional_text(explanations, "wrong_answer", maximum=24_000)
    rendered_explanation = correct if not wrong else f"{correct}\n\n오답 해설\n{wrong}"
    statement_explanations = _content_team_statement_explanations(
        statements,
        correct=correct,
        wrong=wrong or "",
    )
    item_number = content.get("item_number")
    if not isinstance(item_number, int) or isinstance(item_number, bool):
        raise ValueError("Content-team Item number is invalid")
    return ProjectedItemContent(
        profile=profile,
        locale="ko-KR",
        title=None,
        item_number=item_number,
        score_display=_required_text(content, "score_display", maximum=8),
        blocks=tuple(blocks),
        choices=choices,
        answer=answer_number,
        explanation=rendered_explanation,
        concept_source=_required_text(explanations, "concept_source", maximum=12_000),
        authoring_intent=_required_text(explanations, "authoring_intent", maximum=20_000),
        statement_explanations=statement_explanations,
    )


def _image_components_by_visual_ordinal(
    components: list[dict[str, Any]], item_revision_id: str
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for component in components:
        if component.get("component_type") != "IMAGE":
            continue
        ordinal = component.get("ordinal")
        if (
            component.get("item_revision_id") != item_revision_id
            or not isinstance(ordinal, int)
            or ordinal not in {0, 1}
            or ordinal in result
            or component.get("required") is not True
            or component.get("logical_name") != f"content-team-visual-{ordinal}.png"
        ):
            raise ValueError("Item image component identity is invalid")
        artifact = _artifact_pointer(component)
        if (
            artifact.get("schema_ref") != "eom://schemas/generated-item/stimulus-png/3.0"
            or artifact.get("media_type") != "image/png"
        ):
            raise ValueError("Item image component contract is invalid")
        result[ordinal] = component
    return result


def _artifact_pointer(component: dict[str, Any]) -> dict[str, Any]:
    artifact = _object(component.get("artifact"), "Item component Artifact pointer")
    for key in ("artifact_id", "artifact_revision_id"):
        value = artifact.get(key)
        if not isinstance(value, str) or _ID.fullmatch(value) is None:
            raise ValueError("Item component Artifact identity is invalid")
    sha256 = artifact.get("sha256")
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
        raise ValueError("Item component Artifact hash is invalid")
    logical_uri = artifact.get("logical_uri")
    if (
        logical_uri
        != f"nas://artifacts/{artifact['artifact_id']}/{artifact['artifact_revision_id']}"
    ):
        raise ValueError("Item component Artifact URI differs from its identity")
    return artifact


def _content_team_statement_explanations(
    statements: tuple[PreviewStatement, ...], *, correct: str, wrong: str
) -> tuple[PreviewStatementExplanation, ...]:
    if not statements:
        return ()
    combined = "\n".join(value for value in (correct, wrong) if value)
    markers = list(re.finditer(r"(?m)^([ㄱㄴㄷ])\.\s+", combined))
    by_label: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(combined)
        text = combined[marker.end() : end].strip()
        if not text or marker.group(1) in by_label:
            raise ValueError("Content-team statement explanation is invalid")
        by_label[marker.group(1)] = text
    if set(by_label) != {statement.label for statement in statements}:
        raise ValueError("Content-team statement explanations are incomplete")
    return tuple(
        PreviewStatementExplanation(
            statement_id=statement.statement_id, text=by_label[statement.label]
        )
        for statement in statements
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    result = value.get(key)
    if not isinstance(result, list):
        raise ValueError(f"{key} is not an ordered array")
    return result


def _required_text(value: dict[str, Any], key: str, *, maximum: int) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result or len(result) > maximum:
        raise ValueError(f"{key} is invalid")
    return result


def _optional_text(value: dict[str, Any], key: str, *, maximum: int) -> str | None:
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, str) or len(result) > maximum:
        raise ValueError(f"{key} is invalid")
    return result or None
