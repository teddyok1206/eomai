"""Projection from canonical item content into the approved question-template contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn, cast

from eom_catalog_contracts import (
    AssessmentItemContent,
    EquationBlock,
    ImageBlock,
    ParagraphBlock,
    SingleChoiceInteraction,
    StatementSetBlock,
    TableBlock,
    validate_eom_question_template_content,
)
from eom_hwpx_contracts import (
    EquationInput,
    HwpxItemDocument,
    ImageInput,
    ItemInput,
    SolutionInput,
    StatementSet,
    TableData,
)

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode

QUESTION_TEMPLATE_LOGICAL_NAME = "placeholder-item-v1"
QUESTION_TEMPLATE_PROFILE = "eom-question-template-v1"


@dataclass(frozen=True)
class QuestionTemplateProjection:
    document: HwpxItemDocument
    image: ImageBlock


def project_question_template(
    content: AssessmentItemContent,
    *,
    item_revision_id: str,
    item_number: int = 1,
) -> QuestionTemplateProjection:
    """Fail-closed projection for the fixed content-team question template."""

    try:
        validate_eom_question_template_content(content)
    except ValueError as exc:
        _incompatible(str(exc))
    if not isinstance(content.interaction, SingleChoiceInteraction):
        _incompatible("question template requires single-choice content")
    blocks = _index_blocks(content)
    stem = cast(ParagraphBlock, _one(blocks, ParagraphBlock, "paragraph", "stem"))
    prompt = cast(ParagraphBlock, _one(blocks, ParagraphBlock, "paragraph", "prompt"))
    table = cast(TableBlock, _one(blocks, TableBlock, "table", "data"))
    image = cast(ImageBlock, _one(blocks, ImageBlock, "image", "stimulus"))
    equation = cast(EquationBlock, _one(blocks, EquationBlock, "equation", "stimulus"))
    claims = cast(
        StatementSetBlock,
        _one(blocks, StatementSetBlock, "statement_set", "claims"),
    )

    correct_id = content.solution.correct_choice_ids[0]
    correct_index = next(
        (
            index
            for index, choice in enumerate(content.interaction.choices, start=1)
            if choice.choice_id == correct_id
        ),
        None,
    )
    if correct_index is None:
        _incompatible("correct choice pointer does not resolve")
    explanations = {
        value.statement_id: value.text for value in content.solution.statement_explanations
    }
    statement_ids = [value.statement_id for value in claims.statements]

    revision_suffix = item_revision_id.removeprefix("itemrev_")
    if len(revision_suffix) != 32 or any(
        value not in "0123456789abcdef" for value in revision_suffix
    ):
        _incompatible("item revision identity is invalid")
    document = HwpxItemDocument(
        document_id=f"placeholder-{revision_suffix}",
        document_title=content.title,
        item=ItemInput(
            item_number=str(item_number),
            upper_stem=stem.text,
            lower_stem=prompt.text,
            table=TableData(
                rows=(
                    (table.headers[0], table.headers[1], table.headers[2]),
                    (table.rows[0][0], table.rows[0][1], table.rows[0][2]),
                )
            ),
            image=ImageInput(
                source_path="eom-placeholder-image-output.png",
                media_type="image/png",
                sha256=image.artifact.sha256,
                expected_width_px=800,
                expected_height_px=500,
            ),
            equation=EquationInput(
                source_format="hancom-equation-script",
                source=equation.source,
            ),
            statements=StatementSet(
                giyeok=claims.statements[0].text,
                nieun=claims.statements[1].text,
                digeut=claims.statements[2].text,
            ),
            choices=(
                content.interaction.choices[0].text,
                content.interaction.choices[1].text,
                content.interaction.choices[2].text,
                content.interaction.choices[3].text,
                content.interaction.choices[4].text,
            ),
            points="2" if content.score.points == 2 else "3",
        ),
        solution=SolutionInput(
            answer=cast(Literal["1", "2", "3", "4", "5"], str(correct_index)),
            authoring_intent=content.solution.authoring_intent,
            overview=content.solution.explanation,
            statement_explanations=StatementSet(
                giyeok=explanations[statement_ids[0]],
                nieun=explanations[statement_ids[1]],
                digeut=explanations[statement_ids[2]],
            ),
        ),
    )
    return QuestionTemplateProjection(document=document, image=image)


Block = ParagraphBlock | TableBlock | ImageBlock | EquationBlock | StatementSetBlock


def _index_blocks(content: AssessmentItemContent) -> dict[tuple[str, str], list[Block]]:
    index: dict[tuple[str, str], list[Block]] = {}
    for block in content.body:
        index.setdefault((block.type, block.purpose), []).append(block)
    return index


def _one(
    blocks: dict[tuple[str, str], list[Block]],
    block_type: type[ParagraphBlock]
    | type[TableBlock]
    | type[ImageBlock]
    | type[EquationBlock]
    | type[StatementSetBlock],
    type_name: str,
    purpose: str,
) -> Block:
    values = blocks.get((type_name, purpose), [])
    if len(values) != 1:
        _incompatible(f"question template requires exactly one {purpose} {block_type.__name__}")
    if not isinstance(values[0], block_type):
        _incompatible(f"question template block type mismatch for {purpose}")
    return values[0]


def _incompatible(message: str) -> NoReturn:
    raise HwpxManagerError(HwpxManagerErrorCode.HWPX_TEMPLATE_CONTENT_INCOMPATIBLE, message)
