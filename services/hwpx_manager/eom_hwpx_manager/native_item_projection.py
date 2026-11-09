"""Project an already resolved canonical Item into local editable publication values."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    AssessmentItemContent,
    EquationBlock,
    ImageBlock,
    MediaArtifactPointer,
    ParagraphBlock,
    SingleChoiceInteraction,
    StatementSetBlock,
    TableBlock,
)
from eom_hwpx_contracts.curated_occurrences import NativeItemRenderRequestV2
from eom_hwpx_contracts.native_item import (
    NativeItemBlock,
    NativeItemChoice,
    NativeItemEquation,
    NativeItemImage,
    NativeItemParagraph,
    NativeItemRenderRequest,
    NativeItemStatement,
    NativeItemStatements,
    NativeItemTable,
)
from eom_hwpx_contracts.validation import validate_contract


@dataclass(frozen=True)
class NativeItemImageBinding:
    """One source use; staging may deduplicate bytes only after resolving every pointer."""

    image: NativeItemImage
    source: MediaArtifactPointer


@dataclass(frozen=True)
class NativeItemProjection:
    document: NativeItemRenderRequest
    images: tuple[NativeItemImageBinding, ...]


def project_native_item(
    content: AssessmentItemContent,
    *,
    build_id: str,
    item_revision_id: str,
    source_sha256: str,
    effective_content_sha256: str,
    item_number: int = 1,
    document_type: type[NativeItemRenderRequest] = NativeItemRenderRequest,
) -> NativeItemProjection:
    """Preserve body order without imposing the old fixed table/image/equation template."""
    blocks: list[NativeItemBlock] = []
    images: list[NativeItemImageBinding] = []
    statement_labels: dict[str, str] = {}
    for block in content.body:
        if isinstance(block, ParagraphBlock):
            blocks.append(
                NativeItemParagraph(block_id=block.block_id, purpose=block.purpose, text=block.text)
            )
        elif isinstance(block, EquationBlock):
            blocks.append(
                NativeItemEquation(
                    block_id=block.block_id, notation=block.notation, source=block.source
                )
            )
        elif isinstance(block, TableBlock):
            blocks.append(
                NativeItemTable(
                    block_id=block.block_id,
                    caption=block.caption,
                    headers=block.headers,
                    rows=block.rows,
                )
            )
        elif isinstance(block, ImageBlock):
            suffix = "png" if block.artifact.media_type == "image/png" else "jpg"
            image = NativeItemImage(
                block_id=block.block_id,
                ordinal=len(images) + 1,
                local_file=f"images/{block.artifact.sha256.removeprefix('sha256:')}.{suffix}",
                sha256=block.artifact.sha256,
                media_type=block.artifact.media_type,
                width_px=block.width_px,
                height_px=block.height_px,
            )
            blocks.append(image)
            images.append(NativeItemImageBinding(image=image, source=block.artifact))
        elif isinstance(block, StatementSetBlock):
            statements = tuple(
                NativeItemStatement(statement_id=row.statement_id, label=row.label, text=row.text)
                for row in block.statements
            )
            blocks.append(NativeItemStatements(block_id=block.block_id, statements=statements))
            statement_labels.update((row.statement_id, row.label) for row in block.statements)
        else:
            raise ValueError("unsupported canonical Item publication block")
    choices = (
        tuple(
            NativeItemChoice(choice_id=row.choice_id, label=row.label, text=row.text)
            for row in content.interaction.choices
        )
        if isinstance(content.interaction, SingleChoiceInteraction)
        else ()
    )
    document = document_type(
        build_id=build_id,
        item_revision_id=item_revision_id,
        source_sha256=source_sha256,
        effective_content_sha256=effective_content_sha256,
        item_number=item_number,
        title=content.title,
        points=content.score.points,
        body=tuple(blocks),
        choices=choices,
        accepted_answers=content.solution.accepted_answers,
        correct_choice_id=content.solution.correct_choice_ids[0] if choices else None,
        authoring_intent=content.solution.authoring_intent,
        explanation=content.solution.explanation,
        statement_explanations=tuple(
            NativeItemStatement(
                statement_id=row.statement_id,
                label=statement_labels[row.statement_id],
                text=row.text,
            )
            for row in content.solution.statement_explanations
        ),
    )
    validate_contract(
        "native-item-render-request-v2"
        if isinstance(document, NativeItemRenderRequestV2)
        else "native-item-render-request",
        document.model_dump(mode="json"),
    )
    return NativeItemProjection(document, tuple(images))
