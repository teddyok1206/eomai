"""Admit all original-page crop metadata before bounded, unique-page PNG reads."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceSourcePageCropReviewV2,
    LocalImageScienceSourcePageCropReviewV3,
    ScienceSourcePageCropRegion,
    SourcePageCropReview,
    validate_contract,
    validate_source_page_crop_sources,
    validate_source_page_region_sources,
)
from eom_image_contracts.source_page_crops import source_page_crop_protocol
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import resolve_sdxl_training_sources
from eom_orchestrator.source_page_crop_expansion_inputs import (
    resolve_science_visual_expansion_lineage,
    resolve_source_page_crop_expansion,
)

_MAX_BATCH_BYTES = 128 * 1024**2
_MAX_BATCH_PAGES = 64


@dataclass(frozen=True, slots=True)
class ScienceSourcePageCropRead:
    pointer: ImageEvaluationArtifactMember
    size_bytes: int
    selections: tuple[ScienceSourcePageCropRegion, ...]


def prepare_source_page_crop_reads(
    engine: Engine, review: SourcePageCropReview
) -> tuple[ScienceSourcePageCropRead, ...]:
    """Read-only provenance admission; rejected metadata consumes no page PNG bytes."""
    protocol = source_page_crop_protocol(review)
    validate_contract(protocol.review_contract, review.model_dump(mode="json"))
    review = type(review).model_validate(review.model_dump(mode="json"))
    lineage = resolve_sdxl_training_sources(
        engine,
        crop_set_pointer=review.basis_crop_set,
        authorization_pointer=review.training_authorization,
    )
    if isinstance(review, LocalImageScienceSourcePageCropReviewV3):
        if review.training_authorization != lineage.crop_set.training_authorization or (
            lineage.authorization.approved_at > review.created_at
        ):
            raise ValueError("SCIENCE_SOURCE_CROP_REGION_AUTHORIZATION_MISMATCH")
        plans = lineage.plans
        results = lineage.results
        pointers = tuple(pilot.pilot_result for pilot in lineage.inventory.pilot_results)
        if review.supplemental_pilots:
            expansion = resolve_science_visual_expansion_lineage(
                engine,
                supplemental_pilots=review.supplemental_pilots,
                basis=lineage,
                observed_at=review.created_at,
            )
            plans = (*plans, *expansion.plans)
            results = (*results, *expansion.results)
            pointers = (*pointers, *(pilot.pilot_result for pilot in review.supplemental_pilots))
        validate_source_page_region_sources(
            review, plans=plans, results=results, result_pointers=pointers
        )
    elif isinstance(review, LocalImageScienceSourcePageCropReviewV2):
        results = resolve_source_page_crop_expansion(engine, review, lineage).results
    else:
        validate_source_page_crop_sources(
            review,
            crop_set=lineage.crop_set,
            authorization=lineage.authorization,
            inventory=lineage.inventory,
            plans=lineage.plans,
            results=lineage.results,
        )
        results = lineage.results
    page_sizes = {
        (page.document_id, page.physical_page): page.size_bytes
        for result in results
        for page in result.page_images
    }
    by_page: dict[ImageEvaluationArtifactMember, list[ScienceSourcePageCropRegion]] = {}
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
