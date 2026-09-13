"""Canonical student-visible material requirement for content-team Items."""

from __future__ import annotations

from typing import Literal

from eom_hwpx_contracts import ContentTeamEditorialDraftContract
from pydantic import model_validator

from eom_catalog_contracts.models import FrozenModel

ContentTeamMaterialForm = Literal[
    "AUTO",
    "TEXT",
    "DATA",
    "TABLE",
    "IMAGE",
    "MIXED",
    "INQUIRY",
]
ContentTeamRetrievalElement = Literal["choice", "image", "paragraph", "table"]


class ContentTeamMaterialRequirementV1(FrozenModel):
    """Reviewed requirement for the material visible to the candidate.

    ``image_mode`` is an execution capability.  This value describes the authored content and
    therefore keeps native tables distinct from generated raster images.
    """

    schema_version: Literal["content-team-material-requirement/1.0"] = (
        "content-team-material-requirement/1.0"
    )
    form: ContentTeamMaterialForm
    panel_count: int | None

    @model_validator(mode="after")
    def coherent_panel_count(self) -> ContentTeamMaterialRequirementV1:
        if self.form in {"AUTO", "TEXT", "DATA", "INQUIRY"}:
            if self.panel_count is not None:
                raise ValueError(f"{self.form} material cannot declare a panel count")
        elif self.form in {"TABLE", "IMAGE"}:
            if self.panel_count not in {1, 2}:
                raise ValueError(f"{self.form} material requires one or two panels")
        elif self.panel_count != 2:
            raise ValueError("MIXED material requires exactly two panels")
        return self

    @property
    def image_mode(self) -> Literal["skip", "required"]:
        """Return whether the workflow must make the image role available."""

        return "required" if self.form in {"AUTO", "IMAGE", "MIXED"} else "skip"


def content_team_material_required_retrieval_elements(
    requirement: ContentTeamMaterialRequirementV1,
) -> tuple[ContentTeamRetrievalElement, ...]:
    """Return the canonical sorted RAG filter for one reviewed material requirement."""

    elements: set[ContentTeamRetrievalElement] = {"choice", "paragraph"}
    if requirement.form in {"IMAGE", "MIXED"}:
        elements.add("image")
    if requirement.form in {"TABLE", "MIXED"}:
        elements.add("table")
    return tuple(sorted(elements))


def validate_content_team_material_selection(
    requirement: ContentTeamMaterialRequirementV1,
    *,
    task_type: str,
    allowed_forms: tuple[str, ...],
    inquiry_required: bool,
) -> None:
    """Validate one mock-exam material choice against its released allowed set.

    The allowed tuple is ordered policy data with at most six members.  Selection is a single
    bounded membership check; the tuple remains intact so choosing a non-first allowed form does
    not rewrite the released policy pointer or its preference order.
    """

    if requirement.form != task_type:
        raise ValueError("material requirement differs from the selected task type")
    if requirement.form not in allowed_forms:
        raise ValueError("selected material form is outside the released slot policy")
    if (requirement.form == "INQUIRY") != inquiry_required:
        raise ValueError("selected material form differs from the slot inquiry requirement")


def validate_content_team_material_requirement(
    requirement: ContentTeamMaterialRequirementV1,
    draft: ContentTeamEditorialDraftContract,
) -> None:
    """Fail closed when an authored draft differs from the reviewed material form.

    Visuals are a bounded ordered tuple, so this check is O(v + b) time and O(1) auxiliary space,
    where ``v <= 2`` and ``b <= 2`` are the visual and labeled-block counts.
    """

    if requirement.form == "AUTO":
        return

    visual_kinds = tuple(visual.kind for visual in draft.visuals)
    data_block_count = sum(block.kind == "DATA" for block in draft.labeled_blocks)
    expected: tuple[str, tuple[str, ...], bool, int | None] = {
        "TEXT": ("NONE", (), False, 0),
        "DATA": ("NONE", (), False, 1),
        "TABLE": (
            "TABLE_ONLY" if requirement.panel_count == 1 else "TABLE_TABLE",
            ("TABLE",) * (requirement.panel_count or 0),
            False,
            0,
        ),
        "IMAGE": (
            "IMAGE_ONLY" if requirement.panel_count == 1 else "IMAGE_IMAGE",
            ("IMAGE",) * (requirement.panel_count or 0),
            False,
            1,
        ),
        "MIXED": (draft.visual_layout, visual_kinds, False, 0),
        "INQUIRY": ("INQUIRY_BOX", (), True, 0),
    }[requirement.form]
    expected_layout, expected_kinds, expects_inquiry, expected_data_blocks = expected

    if requirement.form == "MIXED":
        if draft.visual_layout not in {"IMAGE_TABLE", "TABLE_IMAGE"} or set(visual_kinds) != {
            "IMAGE",
            "TABLE",
        }:
            raise ValueError("MIXED material requires one IMAGE and one TABLE panel")
    elif draft.visual_layout != expected_layout or visual_kinds != expected_kinds:
        raise ValueError(f"authored material differs from reviewed {requirement.form} form")

    if (draft.inquiry is not None) != expects_inquiry:
        raise ValueError(f"authored inquiry differs from reviewed {requirement.form} form")
    if expected_data_blocks is not None and data_block_count != expected_data_blocks:
        raise ValueError(f"authored DATA blocks differ from reviewed {requirement.form} form")
