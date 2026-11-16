"""Resolve small selections into existing split/merge rules, with no I/O or publication.

The storage owner must authorize and resolve exact inputs before calling this function,
then reauthorize and CAS all input heads when adopting the returned manifests together.
Server-reserved output identities/time must be reused when the same command resumes.
"""

from dataclasses import dataclass
from datetime import datetime

from eom_catalog_contracts.kakao_question import (
    KakaoQuestionBlock,
    KakaoQuestionManifest,
    KakaoQuestionText,
)
from eom_catalog_contracts.kakao_question_composition import (
    KakaoCompositionSelection,
    KakaoQuestionComposition,
    KakaoQuestionMerge,
    KakaoWholeBlockSelection,
)

from eom_catalog_service.kakao_question_editing import (
    ResolvedKakaoQuestionSource,
    merge_questions,
    split_question,
)


@dataclass(frozen=True)
class ResolvedKakaoCompositionQuestion:
    manifest: KakaoQuestionManifest
    resource_version: int


def _select_block(
    selection: KakaoCompositionSelection,
    blocks: dict[str, KakaoQuestionBlock],
    *,
    new_block_id: str,
) -> KakaoQuestionBlock:
    block = blocks.get(selection.block_id)
    if block is None:
        raise ValueError("KAKAO_ARCHIVE_COMPOSITION_BLOCK_MISSING")
    if isinstance(selection, KakaoWholeBlockSelection):
        return block
    if not isinstance(block, KakaoQuestionText) or not (
        block.start_codepoint
        <= selection.start_codepoint
        < selection.end_codepoint
        <= block.end_codepoint
    ):
        raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
    if (selection.start_codepoint, selection.end_codepoint) == (
        block.start_codepoint,
        block.end_codepoint,
    ):
        return block
    # Display overrides are not source offsets. Never silently drop or slice an override.
    if block.display_override is not None:
        raise ValueError("KAKAO_ARCHIVE_SPLIT_DISPLAY_OVERRIDE")
    return KakaoQuestionText.model_validate(
        block.model_dump()
        | {
            "block_id": new_block_id,
            "start_codepoint": selection.start_codepoint,
            "end_codepoint": selection.end_codepoint,
        }
    )


def prepare_question_composition(
    command: KakaoQuestionComposition,
    inputs: tuple[ResolvedKakaoCompositionQuestion, ...],
    *,
    new_ids: tuple[tuple[str, str], ...],
    actor_id: str,
    created_at: datetime,
    sources: tuple[ResolvedKakaoQuestionSource, ...],
) -> tuple[KakaoQuestionManifest, ...]:
    """Pure preparation only: complete coverage, exact parents, server identities, stable order."""
    expected = command.inputs if isinstance(command, KakaoQuestionMerge) else (command.input,)
    by_id = {item.manifest.question_id: item for item in inputs}
    if (
        len(by_id) != len(inputs)
        or set(by_id) != {item.question_id for item in expected}
        or any(
            by_id[item.question_id].manifest.question_revision_id != item.question_revision_id
            or type(by_id[item.question_id].resource_version) is not int
            or by_id[item.question_id].resource_version != item.resource_version
            for item in expected
        )
    ):
        raise ValueError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    ordered = tuple(by_id[item.question_id].manifest for item in expected)
    if any(
        item.source_binding_id != command.source_binding_id or item.room_id != command.room_id
        for item in ordered
    ):
        raise ValueError("KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID")
    if isinstance(command, KakaoQuestionMerge):
        if len(new_ids) != 1:
            raise ValueError("KAKAO_ARCHIVE_COMPOSITION_RESERVATION_INVALID")
        return (
            merge_questions(
                ordered,
                expected_revision_ids=tuple(item.question_revision_id for item in expected),
                question_id=new_ids[0][0],
                question_revision_id=new_ids[0][1],
                actor_id=actor_id,
                created_at=created_at,
                sources=sources,
            ),
        )
    if len(new_ids) != len(command.partitions):
        raise ValueError("KAKAO_ARCHIVE_COMPOSITION_RESERVATION_INVALID")
    blocks = {block.block_id: block for block in ordered[0].ordered_blocks}
    partitions = tuple(
        tuple(
            _select_block(selection, blocks, new_block_id=f"{ids[0]}:{position}")
            for position, selection in enumerate(partition)
        )
        for partition, ids in zip(command.partitions, new_ids, strict=True)
    )
    return split_question(
        ordered[0],
        partitions,
        expected_revision_id=command.input.question_revision_id,
        new_ids=new_ids,
        actor_id=actor_id,
        created_at=created_at,
        sources=sources,
    )
