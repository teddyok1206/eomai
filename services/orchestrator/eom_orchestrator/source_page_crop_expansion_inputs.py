"""Resolve complete supplemental crop provenance before any page pixels are read."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts import ScienceAssessmentWebCorpusManifestV2
from eom_catalog_contracts import validate_contract as validate_catalog_contract
from eom_catalog_service.science_visual_expansion_planning import (
    validate_science_visual_expansion_plan_sources,
)
from eom_catalog_service.science_visual_pilot import ScienceVisualPilotPlanningError
from eom_image_contracts import (
    LocalImageScienceCorpusVisualPilotPlanV4,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceSourcePageCropReviewV2,
    ScienceSourcePageCropSupplementalPilot,
    content_json_bytes,
    validate_contract,
    validate_science_visual_pilot_result,
)
from eom_image_contracts.source_page_crops import validate_source_page_crop_selection_sources
from pydantic import BaseModel
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import ResolvedSdxlTrainingSources

_MAX_METADATA_BYTES = 8 * 1024**2


@dataclass(frozen=True, slots=True)
class ResolvedScienceSourceCropExpansion:
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV4, ...]
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...]


def _document[Document: BaseModel](raw: bytes, contract: str, model: type[Document]) -> Document:
    value = json.loads(raw)
    validate_contract(contract, value)
    document = model.model_validate(value)
    canonical = content_json_bytes(document.model_dump(mode="json"))
    if raw not in (canonical, canonical + b"\n"):
        raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_NONCANONICAL_METADATA")
    return document


def resolve_source_page_crop_expansion(
    engine: Engine,
    review: LocalImageScienceSourcePageCropReviewV2,
    basis: ResolvedSdxlTrainingSources,
) -> ResolvedScienceSourceCropExpansion:
    """Admit reviewed selections after the same metadata boundary used for discovery."""
    if review.training_authorization != basis.crop_set.training_authorization:
        raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_AUTHORIZATION_MISMATCH")
    lineage = resolve_science_visual_expansion_lineage(
        engine,
        supplemental_pilots=review.supplemental_pilots,
        basis=basis,
        observed_at=review.created_at,
    )
    validate_source_page_crop_selection_sources(
        review,
        plans=lineage.plans,
        results=lineage.results,
        result_pointers=tuple(pair.pilot_result for pair in review.supplemental_pilots),
    )
    return lineage


def resolve_science_visual_expansion_lineage(
    engine: Engine,
    *,
    supplemental_pilots: tuple[ScienceSourcePageCropSupplementalPilot, ...],
    basis: ResolvedSdxlTrainingSources,
    observed_at: datetime,
) -> ResolvedScienceSourceCropExpansion:
    """Shared read-only discovery/crop admission; never invent a review to read metadata."""
    if (
        not 2 <= len(supplemental_pilots) <= 4
        or observed_at.tzinfo is None
        or observed_at.utcoffset() != UTC.utcoffset(observed_at)
        or basis.authorization.approved_at > observed_at
    ):
        raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_INPUT_INVALID")
    supplemental_pilots = tuple(
        ScienceSourcePageCropSupplementalPilot.model_validate(pair.model_dump(mode="json"))
        for pair in supplemental_pilots
    )
    for pointers in (
        tuple(pair.pilot_plan for pair in supplemental_pilots),
        tuple(pair.pilot_result for pair in supplemental_pilots),
    ):
        if len(
            {
                (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)
                for pointer in pointers
            }
        ) != len(pointers):
            raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_REPEATED_PILOT")
    pointers = (
        basis.authorization.corpus_manifest,
        *(
            pointer
            for pair in supplemental_pilots
            for pointer in (pair.pilot_plan, pair.pilot_result)
        ),
    )
    payloads = resolve_control_artifact_members(
        engine,
        tuple(BoundedControlArtifactRead(pointer, _MAX_METADATA_BYTES) for pointer in pointers),
    )
    corpus_value = json.loads(payloads[0])
    validate_catalog_contract("science-assessment-web-corpus-manifest-v2", corpus_value)
    # Catalog's frozen corpus model enforces its own identity/semantic hash. The typed
    # authorization pointer and indexed resolver have already enforced its raw SHA/schema.
    corpus = ScienceAssessmentWebCorpusManifestV2.model_validate(corpus_value)
    plans = tuple(
        _document(
            payloads[1 + 2 * index],
            "science-corpus-visual-pilot-plan-v4",
            LocalImageScienceCorpusVisualPilotPlanV4,
        )
        for index in range(len(supplemental_pilots))
    )
    results = tuple(
        _document(
            payloads[2 + 2 * index],
            "science-corpus-visual-pilot-result",
            LocalImageScienceCorpusVisualPilotResult,
        )
        for index in range(len(supplemental_pilots))
    )
    if (
        len({plan.campaign_id for plan in plans}) != 1
        or tuple(plan.campaign_shard_index for plan in plans) != tuple(range(len(plans)))
        or any(plan.campaign_shard_count != len(plans) for plan in plans)
        or len({result.pilot_id for result in results}) != len(results)
    ):
        raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_COVERAGE_MISMATCH")
    source_ids: set[str] = set()
    source_hashes: set[str] = set()
    partitions: dict[str, str] = {}
    predecessors = tuple(pilot.pilot_plan for pilot in basis.inventory.pilot_results)
    for plan, result in zip(plans, results, strict=True):
        try:
            validate_science_visual_expansion_plan_sources(
                plan,
                corpus=corpus,
                authorization=basis.authorization,
                authorization_pointer=basis.crop_set.training_authorization,
                predecessor_plans=basis.plans,
                predecessor_plan_pointers=predecessors,
            )
        except ScienceVisualPilotPlanningError as exc:
            raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_SOURCE_ADMISSION_FAILED") from exc
        validate_science_visual_pilot_result(plan, result)
        if (
            result.status != "SUCCEEDED"
            or result.started_at < plan.created_at
            or result.completed_at > observed_at
        ):
            raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_RESULT_MISMATCH")
        for source in plan.selected_sources:
            if source.document_id in source_ids or source.pdf.sha256 in source_hashes:
                raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_REPEATED_SOURCE")
            source_ids.add(source.document_id)
            source_hashes.add(source.pdf.sha256)
            if (
                partitions.setdefault(source.exam_group_sha256, source.partition)
                != source.partition
            ):
                raise ValueError("SCIENCE_SOURCE_CROP_EXPANSION_PARTITION_LEAKAGE")
    return ResolvedScienceSourceCropExpansion(plans, results)
