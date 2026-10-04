"""Metadata-first native PDF input admission over the existing canonical source owner."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from eom_image_contracts.science_corpus_visual import ScienceVisualPilotSource
from eom_image_contracts.source_page_crops import (
    ScienceSourcePageCropRegion,
    SourcePageCropReview,
    parse_source_page_crop_review,
)
from eom_image_contracts.source_pdf_crops import (
    LocalImageScienceSourcePdfCropCommand,
    select_native_source_pdf_regions,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.source_page_crop_inputs import resolve_source_page_crop_provenance


@dataclass(frozen=True, slots=True)
class ScienceSourcePdfCropRead:
    source: ScienceVisualPilotSource
    selections: tuple[ScienceSourcePageCropRegion, ...]


@dataclass(frozen=True, slots=True)
class PreparedScienceSourcePdfCrops:
    command: LocalImageScienceSourcePdfCropCommand
    review: SourcePageCropReview
    reads: tuple[ScienceSourcePdfCropRead, ...]


def prepare_source_pdf_crop_reads(
    engine: Engine, command: LocalImageScienceSourcePdfCropCommand
) -> PreparedScienceSourcePdfCrops:
    """No PDF/PNG materialization until complete lineage and the native recipe pass."""
    validate_contract("science-source-pdf-crop-command", command.model_dump(mode="json"))
    command = LocalImageScienceSourcePdfCropCommand.model_validate(command.model_dump(mode="json"))
    raw = resolve_control_artifact_member(engine, command.source_review, maximum_bytes=2 * 1024**2)
    review = parse_source_page_crop_review(command.source_review, raw)
    selected = select_native_source_pdf_regions(command, review)
    provenance = resolve_source_page_crop_provenance(engine, review)
    by_document = {source.document_id: source for source in provenance.pdf_sources}
    by_pdf: dict[str, list[ScienceSourcePageCropRegion]] = {}
    for selection in selected:
        source = by_document[selection.document_id]
        if (
            source.partition != "TRAIN"
            or source.pdf != selection.source_document
            or (
                source.exam_group_sha256 != selection.exam_group_sha256
                or source.bytes > 64 * 1024**2
            )
        ):
            raise ValueError("NATIVE_PDF_CROP_SOURCE_METADATA_MISMATCH")
        by_pdf.setdefault(source.document_id, []).append(selection)
    reads = tuple(
        ScienceSourcePdfCropRead(by_document[identifier], tuple(by_pdf[identifier]))
        for identifier in sorted(by_pdf)
    )
    if sum(read.source.bytes for read in reads) > 128 * 1024**2:
        raise ValueError("NATIVE_PDF_CROP_INPUT_BYTE_BUDGET_EXCEEDED")
    return PreparedScienceSourcePdfCrops(command, review, reads)


def iter_source_pdf_crop_payloads(
    engine: Engine, prepared: PreparedScienceSourcePdfCrops
) -> Iterator[tuple[ScienceSourcePdfCropRead, bytes]]:
    """One bounded indexed read per unique PDF; no reserved pages or N+1 lookup."""
    reads = prepared.reads
    selected = select_native_source_pdf_regions(prepared.command, prepared.review)
    expected_by_id = {selection.selection_id: selection for selection in selected}
    actual = tuple(selection for read in reads for selection in read.selections)
    if (
        not reads
        or len({read.source.pdf for read in reads}) != len(reads)
        or len(actual) != len(expected_by_id)
        or {selection.selection_id: selection for selection in actual} != expected_by_id
        or any(
            read.source.partition != "TRAIN"
            or not read.selections
            or any(
                selection.source_document != read.source.pdf
                or selection.document_id != read.source.document_id
                or selection.exam_group_sha256 != read.source.exam_group_sha256
                for selection in read.selections
            )
            for read in reads
        )
        or (
            sum(read.source.bytes for read in reads) > 128 * 1024**2
            or any(not 1024 <= read.source.bytes <= 64 * 1024**2 for read in reads)
        )
    ):
        raise ValueError("NATIVE_PDF_CROP_READS_INVALID")
    payloads = resolve_control_artifact_members(
        engine,
        tuple(BoundedControlArtifactRead(read.source.pdf, read.source.bytes) for read in reads),
    )
    for read, raw in zip(reads, payloads, strict=True):
        if len(raw) != read.source.bytes:
            raise ValueError("NATIVE_PDF_CROP_SOURCE_SIZE_MISMATCH")
        yield read, raw
