"""Catalog-owned deterministic planning for the science-corpus visual pilot.

Selection is one stable pass over at most 5,000 immutable corpus documents. Documents are grouped
by exam identity before partitioning, indexed by `(partition, subject, issuer)`, ranked once, and
then consumed with per-stratum offsets. The operation is O(n log n) time and O(n) space; no PDF
bytes are copied or read at this boundary.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Literal

from eom_catalog_contracts import (
    ScienceAssessmentCorpusDocument,
    ScienceAssessmentWebCorpusManifestV2,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotPlan,
    ScienceVisualGuidanceAuthority,
    ScienceVisualPilotSource,
    ScienceVisualToolSet,
    content_sha256,
    validate_science_visual_authorization_plan,
)

ScienceVisualPartitionName = Literal["HOLDOUT", "TRAIN", "VALIDATION"]

_PARTITION_CYCLE: tuple[ScienceVisualPartitionName, ...] = (
    "HOLDOUT",
    "VALIDATION",
    "TRAIN",
    "TRAIN",
    "TRAIN",
    "TRAIN",
)


class ScienceVisualPilotPlanningError(RuntimeError):
    """Stable planning error for an unusable bounded corpus sample."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _exam_group_sha256(document: ScienceAssessmentCorpusDocument) -> str:
    return content_sha256(
        {
            "issuer_type": document.issuer_type,
            "administration_year": document.administration_year,
            "grade": document.grade,
            "session_label": document.session_label,
        }
    )


def _group_partitions(
    documents: tuple[ScienceAssessmentCorpusDocument, ...],
    *,
    selection_seed_sha256: str,
) -> dict[str, ScienceVisualPartitionName]:
    groups = {_exam_group_sha256(document) for document in documents}
    ranked = sorted(
        groups,
        key=lambda value: hashlib.sha256(f"{selection_seed_sha256}:{value}".encode()).hexdigest(),
    )
    return {
        value: _PARTITION_CYCLE[index % len(_PARTITION_CYCLE)] for index, value in enumerate(ranked)
    }


def _rank(document: ScienceAssessmentCorpusDocument, *, selection_seed_sha256: str) -> str:
    return hashlib.sha256(
        f"{selection_seed_sha256}:{document.sha256}:{document.document_id}".encode()
    ).hexdigest()


def _select_partition(
    *,
    pools: dict[tuple[str, str], tuple[ScienceAssessmentCorpusDocument, ...]],
    count: int,
    remaining_page_budget: int,
) -> tuple[tuple[ScienceAssessmentCorpusDocument, ...], int]:
    offsets = {key: 0 for key in pools}
    selected: list[ScienceAssessmentCorpusDocument] = []
    while len(selected) < count:
        progress = False
        for key in sorted(pools):
            values = pools[key]
            index = offsets[key]
            while index < len(values) and values[index].page_count > remaining_page_budget:
                index += 1
            offsets[key] = index
            if index >= len(values):
                continue
            document = values[index]
            offsets[key] = index + 1
            selected.append(document)
            remaining_page_budget -= document.page_count
            progress = True
            if len(selected) == count:
                break
        if not progress:
            raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_PILOT_POPULATION_INSUFFICIENT")
    return tuple(selected), remaining_page_budget


def select_science_visual_pilot_sources(
    documents: tuple[ScienceAssessmentCorpusDocument, ...],
    *,
    selection_seed_sha256: str,
    source_limit: int = 36,
    page_limit: int = 192,
) -> tuple[ScienceVisualPilotSource, ...]:
    """Select a deterministic, grouped, stratified population below 100 PDFs."""

    if not 12 <= source_limit <= 96 or not source_limit % 6 == 0:
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_PILOT_SOURCE_LIMIT_INVALID")
    if not source_limit <= page_limit <= 384:
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_PILOT_PAGE_LIMIT_INVALID")
    if not documents or len({value.sha256 for value in documents}) != len(documents):
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_PILOT_CORPUS_INVALID")
    partitions = _group_partitions(documents, selection_seed_sha256=selection_seed_sha256)
    grouped: dict[
        ScienceVisualPartitionName,
        dict[tuple[str, str], list[ScienceAssessmentCorpusDocument]],
    ] = {
        "TRAIN": defaultdict(list),
        "VALIDATION": defaultdict(list),
        "HOLDOUT": defaultdict(list),
    }
    for document in documents:
        partition = partitions[_exam_group_sha256(document)]
        grouped[partition][(document.subject_family, document.issuer_type)].append(document)
    frozen: dict[
        ScienceVisualPartitionName,
        dict[tuple[str, str], tuple[ScienceAssessmentCorpusDocument, ...]],
    ] = {"TRAIN": {}, "VALIDATION": {}, "HOLDOUT": {}}
    for partition, strata in grouped.items():
        frozen[partition] = {
            key: tuple(
                sorted(
                    values,
                    key=lambda value: _rank(
                        value,
                        selection_seed_sha256=selection_seed_sha256,
                    ),
                )
            )
            for key, values in strata.items()
        }
    quotas = {
        "TRAIN": source_limit * 2 // 3,
        "VALIDATION": source_limit // 6,
        "HOLDOUT": source_limit // 6,
    }
    chosen: list[tuple[ScienceAssessmentCorpusDocument, ScienceVisualPartitionName]] = []
    remaining_pages = page_limit
    for partition in ("HOLDOUT", "VALIDATION", "TRAIN"):
        selected, remaining_pages = _select_partition(
            pools=frozen[partition],
            count=quotas[partition],
            remaining_page_budget=remaining_pages,
        )
        chosen.extend((document, partition) for document in selected)
    sources = tuple(
        sorted(
            (
                ScienceVisualPilotSource(
                    document_id=document.document_id,
                    source_file_id=document.source.source_file_id,
                    pdf=ImageEvaluationArtifactMember(
                        artifact_id=document.source.artifact_id,
                        artifact_revision_id=document.source.artifact_revision_id,
                        member_path=document.source.member_path,
                        schema_ref="eom://schemas/content-intake/source-file/1.0",
                        media_type="application/pdf",
                        sha256=document.sha256,
                    ),
                    bytes=document.bytes,
                    page_count=document.page_count,
                    subject_family=document.subject_family,
                    issuer_type=document.issuer_type,
                    administration_year=document.administration_year,
                    grade=document.grade,
                    session_label=document.session_label,
                    exam_group_sha256=_exam_group_sha256(document),
                    partition=partition,
                )
                for document, partition in chosen
            ),
            key=lambda value: value.document_id,
        )
    )
    if len(sources) != source_limit:
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_PILOT_POPULATION_INSUFFICIENT")
    return sources


def build_science_corpus_training_authorization(
    *,
    corpus: ScienceAssessmentWebCorpusManifestV2,
    corpus_manifest: ImageEvaluationArtifactMember,
    approved_at: datetime,
    approved_by: str,
) -> LocalImageScienceCorpusTrainingAuthorization:
    scope = {
        "schema_version": "local-image-science-corpus-training-authorization/1.0",
        "corpus_manifest": corpus_manifest.model_dump(mode="json"),
        "corpus_id": corpus.corpus_id,
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "acquisition_sha256": corpus.acquisition_sha256,
        "resolution_sha256": corpus.resolution_sha256,
        "resolution_policy_id": corpus.resolution_policy_id,
        "resolution_policy_sha256": corpus.resolution_policy_sha256,
        "authorization_basis": "USER_APPROVED_INTERNAL_EXAM_MATERIALS",
        "permitted_uses": (
            "DETERMINISTIC_PATTERN_ANALYSIS",
            "INTERNAL_SSD1B_LORA_TRAINING",
        ),
        "derivative_output": "LORA_ADAPTER_ONLY",
        "raw_source_export": "FORBIDDEN",
        "state": "APPROVED",
    }
    authorization_identity = content_sha256(scope).removeprefix("sha256:")
    body = {
        **scope,
        "authorization_id": "imgscicorpusauth_" + authorization_identity[:32],
        "revision_number": 1,
        "previous_revision_id": None,
        "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
        "approved_by": approved_by,
    }
    revision_identity = content_sha256(body).removeprefix("sha256:")
    body["authorization_revision_id"] = "imgscicorpusauthrev_" + revision_identity[:32]
    body["authorization_sha256"] = content_sha256(body)
    return LocalImageScienceCorpusTrainingAuthorization.model_validate(body)


def build_science_visual_pilot_plan(
    *,
    corpus: ScienceAssessmentWebCorpusManifestV2,
    corpus_manifest: ImageEvaluationArtifactMember,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    authorization_pointer: ImageEvaluationArtifactMember,
    selection_seed_sha256: str,
    guidance_authorities: tuple[ScienceVisualGuidanceAuthority, ...],
    tools: ScienceVisualToolSet,
    source_commit: str,
    created_at: datetime,
    created_by: str,
    source_limit: int = 36,
    page_limit: int = 192,
    max_visual_candidates: int = 256,
    max_lora_training_crops: int = 24,
) -> LocalImageScienceCorpusVisualPilotPlan:
    if any(value.source_commit != source_commit for value in guidance_authorities):
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_PILOT_GUIDANCE_DRIFT")
    sources = select_science_visual_pilot_sources(
        corpus.documents,
        selection_seed_sha256=selection_seed_sha256,
        source_limit=source_limit,
        page_limit=page_limit,
    )
    body = {
        "schema_version": "local-image-science-corpus-visual-pilot-plan/1.0",
        "corpus_manifest": corpus_manifest.model_dump(mode="json"),
        "corpus_id": corpus.corpus_id,
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "acquisition_sha256": corpus.acquisition_sha256,
        "resolution_sha256": corpus.resolution_sha256,
        "resolution_policy_id": corpus.resolution_policy_id,
        "resolution_policy_sha256": corpus.resolution_policy_sha256,
        "training_authorization": authorization_pointer.model_dump(mode="json"),
        "selection_algorithm": "SCIENCE_VISUAL_STRATIFIED_SHA256_V1",
        "selection_seed_sha256": selection_seed_sha256,
        "selected_sources": tuple(value.model_dump(mode="json") for value in sources),
        "max_page_images": sum(value.page_count for value in sources),
        "max_visual_candidates": max_visual_candidates,
        "max_lora_training_crops": max_lora_training_crops,
        "page_render_dpi": 144,
        "locator_revision": "science-corpus-visual-locator/1.0",
        "guidance_authorities": tuple(
            value.model_dump(mode="json") for value in guidance_authorities
        ),
        "tools": tools.model_dump(mode="json"),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["pilot_id"] = "imgscivispilot_" + identity[:32]
    body["plan_sha256"] = content_sha256(body)
    plan = LocalImageScienceCorpusVisualPilotPlan.model_validate(body)
    validate_science_visual_authorization_plan(authorization, plan)
    return plan
