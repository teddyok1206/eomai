"""Resolve pinned science-visual campaign inputs at the Orchestrator boundary.

The dominant access pattern is a bounded key lookup by attempt ID followed by
ordered iteration over campaign shard indexes.  Candidate membership is checked
with a set so overlap detection remains O(n) for the campaign size.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    ScienceVisualCampaignPilotResult,
    content_json_bytes,
    validate_contract,
    validate_science_visual_pilot_result,
)
from pydantic import ValidationError

MAX_SCIENCE_VISUAL_CAMPAIGN_JSON_BYTES = 16 * 1024 * 1024


class ScienceVisualCampaignResolutionError(RuntimeError):
    """Stable failure that preserves pinned campaign inputs for investigation."""


@dataclass(frozen=True)
class ResolvedScienceVisualCampaign:
    campaign_id: str
    pilots: tuple[ScienceVisualCampaignPilotResult, ...]
    candidate_ids: tuple[str, ...]
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...]
    plan_pointers: tuple[ImageEvaluationArtifactMember, ...]
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...]
    result_pointers: tuple[ImageEvaluationArtifactMember, ...]


def safe_read_science_visual_campaign_member(path: Path) -> bytes:
    """Read one stable, bounded, owner-controlled regular file without following links."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceVisualCampaignResolutionError(
            "SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_MISSING"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_SCIENCE_VISUAL_CAMPAIGN_JSON_BYTES
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceVisualCampaignResolutionError("SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_INVALID")
        chunks = bytearray()
        while len(chunks) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(chunks)))
            if not chunk:
                raise ScienceVisualCampaignResolutionError(
                    "SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_TRUNCATED"
                )
            chunks.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ScienceVisualCampaignResolutionError("SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_CHANGED")
    finally:
        os.close(descriptor)
    return bytes(chunks)


def parse_science_visual_campaign_object(payload: bytes) -> dict[str, object]:
    """Parse a JSON object without accepting scalar or array payloads."""

    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceVisualCampaignResolutionError(
            "SCIENCE_VISUAL_REVIEW_BATCH_JSON_INVALID"
        ) from exc
    if not isinstance(value, dict):
        raise ScienceVisualCampaignResolutionError("SCIENCE_VISUAL_REVIEW_BATCH_JSON_INVALID")
    return value


def resolve_science_visual_campaign(
    attempt_ids: tuple[str, ...],
    *,
    workspace_parent: Path,
    state_root: Path,
) -> ResolvedScienceVisualCampaign:
    """Resolve exact plan/result bytes and immutable pointers for campaign shards."""

    pilots: list[ScienceVisualCampaignPilotResult] = []
    candidate_ids: list[str] = []
    source_documents: set[str] = set()
    campaign_id: str | None = None
    plans: list[LocalImageScienceCorpusVisualPilotPlanV3] = []
    plan_pointers: list[ImageEvaluationArtifactMember] = []
    results: list[LocalImageScienceCorpusVisualPilotResult] = []
    result_pointers: list[ImageEvaluationArtifactMember] = []
    for attempt_id in attempt_ids:
        workspace = workspace_parent / attempt_id
        try:
            stage = parse_science_visual_campaign_object(
                safe_read_science_visual_campaign_member(
                    state_root / f"science-visual-pilot-stage-{attempt_id}.json"
                )
            )
            receipt = parse_science_visual_campaign_object(
                safe_read_science_visual_campaign_member(
                    state_root / f"science-visual-pilot-publication-{attempt_id}.json"
                )
            )
            plan_payload = safe_read_science_visual_campaign_member(
                workspace / "input/visual-pilot-plan.json"
            )
            result_payload = safe_read_science_visual_campaign_member(
                workspace / "manifests/visual-pilot-result.json"
            )
            plan_value = parse_science_visual_campaign_object(plan_payload)
            result_value = parse_science_visual_campaign_object(result_payload)
            validate_contract("science-corpus-visual-pilot-plan-v3", plan_value)
            validate_contract("science-corpus-visual-pilot-result", result_value)
            plan = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(plan_value)
            result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)
            plan_pointer = ImageEvaluationArtifactMember.model_validate(stage["plan"])
            result_pointer = ImageEvaluationArtifactMember.model_validate(
                receipt["result_artifact"]
            )
            if (
                stage.get("schema_version") != "science-visual-pilot-stage-receipt/1.0"
                or receipt.get("schema_version") != "science-visual-pilot-publication-receipt/1.0"
                or receipt.get("attempt_id") != attempt_id
                or plan_pointer.sha256
                != sha256_bytes(content_json_bytes(plan.model_dump(mode="json")))
                or receipt.get("result_file_sha256") != sha256_bytes(result_payload)
                or result.status != "SUCCEEDED"
                or result.plan_sha256 != plan.plan_sha256
            ):
                raise ScienceVisualCampaignResolutionError(
                    "SCIENCE_VISUAL_REVIEW_BATCH_BINDING_INVALID"
                )
            validate_science_visual_pilot_result(plan, result)
            if campaign_id is None:
                campaign_id = plan.campaign_id
            elif plan.campaign_id != campaign_id:
                raise ScienceVisualCampaignResolutionError(
                    "SCIENCE_VISUAL_REVIEW_BATCH_CAMPAIGN_MISMATCH"
                )
            for source in plan.selected_sources:
                if source.document_id in source_documents:
                    raise ScienceVisualCampaignResolutionError(
                        "SCIENCE_VISUAL_REVIEW_BATCH_SOURCE_OVERLAP"
                    )
                source_documents.add(source.document_id)
            pilots.append(
                ScienceVisualCampaignPilotResult(
                    attempt_id=attempt_id,
                    campaign_shard_index=plan.campaign_shard_index,
                    campaign_shard_count=plan.campaign_shard_count,
                    pilot_plan=plan_pointer,
                    pilot_plan_file_sha256=plan_pointer.sha256,
                    pilot_plan_semantic_sha256=plan.plan_sha256,
                    pilot_result=result_pointer,
                    pilot_result_file_sha256=result_pointer.sha256,
                    pilot_result_semantic_sha256=result.result_sha256,
                )
            )
            plans.append(plan)
            plan_pointers.append(plan_pointer)
            results.append(result)
            result_pointers.append(result_pointer)
            candidate_ids.extend(candidate.candidate_id for candidate in result.visual_candidates)
        except ScienceVisualCampaignResolutionError:
            raise
        except (KeyError, TypeError, ValidationError, ValueError) as exc:
            raise ScienceVisualCampaignResolutionError(
                "SCIENCE_VISUAL_REVIEW_BATCH_INPUT_INVALID"
            ) from exc
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ScienceVisualCampaignResolutionError("SCIENCE_VISUAL_REVIEW_BATCH_CANDIDATE_OVERLAP")
    if campaign_id is None:
        raise ScienceVisualCampaignResolutionError("SCIENCE_VISUAL_REVIEW_BATCH_INPUT_INVALID")
    ordered = sorted(
        zip(pilots, plans, plan_pointers, results, result_pointers, strict=True),
        key=lambda value: value[0].campaign_shard_index,
    )
    return ResolvedScienceVisualCampaign(
        campaign_id=campaign_id,
        pilots=tuple(value[0] for value in ordered),
        candidate_ids=tuple(sorted(candidate_ids)),
        plans=tuple(value[1] for value in ordered),
        plan_pointers=tuple(value[2] for value in ordered),
        results=tuple(value[3] for value in ordered),
        result_pointers=tuple(value[4] for value in ordered),
    )
