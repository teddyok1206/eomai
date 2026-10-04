"""Admit all original-page crop metadata before bounded, unique-page PNG reads."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceSourcePageCropReview,
    ScienceSourcePageCropSelection,
    validate_contract,
    validate_source_page_crop_sources,
)
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import resolve_sdxl_training_sources

_MAX_BATCH_BYTES = 128 * 1024**2
_MAX_BATCH_PAGES = 64


@dataclass(frozen=True, slots=True)
class ScienceSourcePageCropRead:
    pointer: ImageEvaluationArtifactMember
    size_bytes: int
    selections: tuple[ScienceSourcePageCropSelection, ...]


def prepare_source_page_crop_reads(
    engine: Engine, review: LocalImageScienceSourcePageCropReview
) -> tuple[ScienceSourcePageCropRead, ...]:
    """Read-only provenance admission; rejected metadata consumes no page PNG bytes."""
    validate_contract("science-source-page-crop-review", review.model_dump(mode="json"))
    review = LocalImageScienceSourcePageCropReview.model_validate(review.model_dump(mode="json"))
    lineage = resolve_sdxl_training_sources(
        engine,
        crop_set_pointer=review.basis_crop_set,
        authorization_pointer=review.training_authorization,
    )
    validate_source_page_crop_sources(
        review,
        crop_set=lineage.crop_set,
        authorization=lineage.authorization,
        inventory=lineage.inventory,
        plans=lineage.plans,
        results=lineage.results,
    )
    page_sizes = {
        (page.document_id, page.physical_page): page.size_bytes
        for result in lineage.results
        for page in result.page_images
    }
    by_page: dict[ImageEvaluationArtifactMember, list[ScienceSourcePageCropSelection]] = {}
    for selection in review.selections:
        by_page.setdefault(selection.source_page, []).append(selection)
    return tuple(
        ScienceSourcePageCropRead(
            pointer,
            page_sizes[(selections[0].document_id, selections[0].physical_page)],
            tuple(selections),
        )
        for pointer, selections in sorted(
            by_page.items(),
            key=lambda pair: (
                pair[0].artifact_id,
                pair[0].artifact_revision_id,
                pair[0].member_path,
            ),
        )
    )


def iter_source_page_crop_payloads(
    engine: Engine, reads: tuple[ScienceSourcePageCropRead, ...]
) -> Iterator[tuple[ScienceSourcePageCropRead, bytes]]:
    """Batch indexed resolution and decode each selected page only once at the CPU boundary."""
    if not reads or len({read.pointer for read in reads}) != len(reads):
        raise ValueError("SCIENCE_SOURCE_CROP_PAGE_READS_INVALID")
    if any(not 64 <= read.size_bytes <= 64 * 1024**2 for read in reads):
        raise ValueError("SCIENCE_SOURCE_CROP_PAGE_SIZE_INVALID")
    start = 0
    while start < len(reads):
        end, size = start, 0
        while end < len(reads) and end - start < _MAX_BATCH_PAGES:
            next_size = reads[end].size_bytes
            if size + next_size > _MAX_BATCH_BYTES:
                break
            size += next_size
            end += 1
        batch = reads[start:end]
        payloads = resolve_control_artifact_members(
            engine,
            tuple(BoundedControlArtifactRead(read.pointer, read.size_bytes) for read in batch),
        )
        for read, raw in zip(batch, payloads, strict=True):
            if len(raw) != read.size_bytes:
                raise ValueError("SCIENCE_SOURCE_CROP_PAGE_SIZE_MISMATCH")
            yield read, raw
        start = end
