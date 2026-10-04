"""Catalog-owned supplemental selection from the same fully pinned science corpus."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from eom_catalog_contracts import ScienceAssessmentWebCorpusManifestV2
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotPlanV4,
    ScienceVisualGuidanceAuthority,
    ScienceVisualLocatorPolicyV2,
    ScienceVisualPilotSource,
    ScienceVisualToolSet,
    content_json_bytes,
    content_sha256,
    science_visual_expansion_campaign_id,
    validate_contract,
    validate_science_visual_authorization_plan,
)

from eom_catalog_service.science_visual_pilot import (
    ScienceVisualPilotPlanningError,
    _exam_group_sha256,
    _group_partitions,
    _select_campaign_sources,
    build_science_visual_pilot_plan_v3,
)


def validate_science_visual_expansion_predecessors(
    *,
    corpus: ScienceAssessmentWebCorpusManifestV2,
    corpus_manifest: ImageEvaluationArtifactMember,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    authorization_pointer: ImageEvaluationArtifactMember,
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...],
    plan_pointers: tuple[ImageEvaluationArtifactMember, ...],
    selection_seed_sha256: str,
    created_at: datetime,
) -> frozenset[str]:
    """Admit every frozen source before excluding any; no PDF or infrastructure access."""
    if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_EXPANSION_TIMESTAMP_INVALID")
    if not 2 <= len(plans) <= 4 or len(plans) != len(plan_pointers):
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_EXPANSION_PREDECESSORS_INVALID")
    if (
        len({plan.campaign_id for plan in plans}) != 1
        or tuple(plan.campaign_shard_index for plan in plans) != tuple(range(len(plans)))
        or any(plan.campaign_shard_count != len(plans) for plan in plans)
        or len(set(plan_pointers)) != len(plan_pointers)
    ):
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_EXPANSION_PREDECESSORS_INVALID")
    by_document = {document.document_id: document for document in corpus.documents}
    partitions = _group_partitions(corpus.documents, selection_seed_sha256=selection_seed_sha256)
    source_ids: set[str] = set()
    source_hashes: set[str] = set()
    for plan, pointer in zip(plans, plan_pointers, strict=True):
        raw = content_json_bytes(plan.model_dump(mode="json"))
        if (
            type(plan) is not LocalImageScienceCorpusVisualPilotPlanV3
            or pointer.schema_ref
            != "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.2"
            or pointer.media_type != "application/json"
            or pointer.member_path != "manifests/visual-pilot-plan.json"
            or pointer.sha256
            not in {
                "sha256:" + hashlib.sha256(payload).hexdigest() for payload in (raw, raw + b"\n")
            }
            or plan.corpus_manifest != corpus_manifest
            or plan.corpus_id != corpus.corpus_id
            or plan.corpus_manifest_sha256 != corpus.manifest_sha256
            or plan.training_authorization != authorization_pointer
            or plan.selection_seed_sha256 != selection_seed_sha256
            or plan.created_at > created_at
        ):
            raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_EXPANSION_PREDECESSOR_MISMATCH")
        validate_science_visual_authorization_plan(authorization, plan)
        for source in plan.selected_sources:
            document = by_document.get(source.document_id)
            if document is None:
                raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_EXPANSION_SOURCE_MISSING")
            pdf = ImageEvaluationArtifactMember(
                artifact_id=document.source.artifact_id,
                artifact_revision_id=document.source.artifact_revision_id,
                member_path=document.source.member_path,
                schema_ref="eom://schemas/content-intake/source-file/1.0",
                media_type="application/pdf",
                sha256=document.sha256,
            )
            if (
                source.document_id in source_ids
                or source.pdf.sha256 in source_hashes
                or source.pdf != pdf
                or source.source_file_id != document.source.source_file_id
                or source.bytes != document.bytes
                or source.page_count != document.page_count
                or source.subject_family != document.subject_family
                or source.issuer_type != document.issuer_type
                or source.administration_year != document.administration_year
                or source.grade != document.grade
                or source.session_label != document.session_label
                or source.exam_group_sha256 != _exam_group_sha256(document)
                or source.partition != partitions[source.exam_group_sha256]
            ):
                raise ScienceVisualPilotPlanningError(
                    "SCIENCE_VISUAL_EXPANSION_FROZEN_SOURCE_MISMATCH"
                )
            source_ids.add(source.document_id)
            source_hashes.add(source.pdf.sha256)
    return frozenset(source_ids)


def select_science_visual_expansion_sources(
    corpus: ScienceAssessmentWebCorpusManifestV2,
    *,
    selection_seed_sha256: str,
    excluded_document_ids: frozenset[str],
    campaign_shard_index: int,
    campaign_shard_count: int,
    source_limit: int = 54,
    page_limit: int = 384,
) -> tuple[ScienceVisualPilotSource, ...]:
    """Use the existing ranked pools; never regroup a prefiltered corpus."""
    if not excluded_document_ids or not excluded_document_ids.issubset(
        {document.document_id for document in corpus.documents}
    ):
        raise ScienceVisualPilotPlanningError("SCIENCE_VISUAL_EXPANSION_EXCLUSIONS_INVALID")
    return _select_campaign_sources(
        corpus.documents,
        selection_seed_sha256=selection_seed_sha256,
        campaign_shard_index=campaign_shard_index,
        campaign_shard_count=campaign_shard_count,
        source_limit=source_limit,
        page_limit=page_limit,
        excluded_document_ids=excluded_document_ids,
    )


def build_science_visual_expansion_plan(
    *,
    corpus: ScienceAssessmentWebCorpusManifestV2,
    corpus_manifest: ImageEvaluationArtifactMember,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    authorization_pointer: ImageEvaluationArtifactMember,
    predecessor_plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...],
    predecessor_plan_pointers: tuple[ImageEvaluationArtifactMember, ...],
    selection_seed_sha256: str,
    campaign_shard_index: int,
    campaign_shard_count: int,
    guidance_authorities: tuple[ScienceVisualGuidanceAuthority, ...],
    tools: ScienceVisualToolSet,
    source_commit: str,
    created_at: datetime,
    created_by: str,
    locator_policy: ScienceVisualLocatorPolicyV2,
    source_limit: int = 54,
    page_limit: int = 384,
    max_visual_candidates: int = 512,
    max_lora_training_crops: int = 24,
) -> LocalImageScienceCorpusVisualPilotPlanV4:
    excluded = validate_science_visual_expansion_predecessors(
        corpus=corpus,
        corpus_manifest=corpus_manifest,
        authorization=authorization,
        authorization_pointer=authorization_pointer,
        plans=predecessor_plans,
        plan_pointers=predecessor_plan_pointers,
        selection_seed_sha256=selection_seed_sha256,
        created_at=created_at,
    )
    basis = build_science_visual_pilot_plan_v3(
        corpus=corpus,
        corpus_manifest=corpus_manifest,
        authorization=authorization,
        authorization_pointer=authorization_pointer,
        selection_seed_sha256=selection_seed_sha256,
        campaign_shard_index=campaign_shard_index,
        campaign_shard_count=campaign_shard_count,
        guidance_authorities=guidance_authorities,
        tools=tools,
        source_commit=source_commit,
        created_at=created_at,
        created_by=created_by,
        locator_policy=locator_policy,
        source_limit=source_limit,
        page_limit=page_limit,
        max_visual_candidates=max_visual_candidates,
        max_lora_training_crops=max_lora_training_crops,
    )
    selected = select_science_visual_expansion_sources(
        corpus,
        selection_seed_sha256=selection_seed_sha256,
        excluded_document_ids=excluded,
        campaign_shard_index=campaign_shard_index,
        campaign_shard_count=campaign_shard_count,
        source_limit=source_limit,
        page_limit=page_limit,
    )
    body = basis.model_dump(mode="json", exclude={"pilot_id", "plan_sha256"})
    body.update(
        schema_version="local-image-science-corpus-visual-pilot-plan/1.3",
        selection_algorithm="SCIENCE_VISUAL_FROZEN_SOURCE_EXPANSION_V1",
        campaign_id=science_visual_expansion_campaign_id(basis, predecessor_plan_pointers),
        predecessor_plans=tuple(
            pointer.model_dump(mode="json") for pointer in predecessor_plan_pointers
        ),
        selected_sources=tuple(source.model_dump(mode="json") for source in selected),
        max_page_images=sum(source.page_count for source in selected),
    )
    body["pilot_id"] = "imgscivispilot_" + content_sha256(body)[7:39]
    body["plan_sha256"] = content_sha256(body)
    plan = LocalImageScienceCorpusVisualPilotPlanV4.model_validate(body)
    validate_contract("science-corpus-visual-pilot-plan-v4", plan.model_dump(mode="json"))
    validate_science_visual_authorization_plan(authorization, plan)
    return plan
