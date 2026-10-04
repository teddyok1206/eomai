"""Supplemental pilot inputs; frozen original partitions and sources are not reinterpreted."""

from __future__ import annotations

from collections import Counter
from typing import Literal, Self

from pydantic import Field, model_validator

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_sha256
from eom_image_contracts.science_corpus_visual import (
    LocalImageScienceCorpusVisualPilotCommandV3,
    LocalImageScienceCorpusVisualPilotPlanV3,
    ScienceVisualPilotSource,
    ScienceVisualStagedSource,
    validate_science_visual_pilot_command_identity,
    validate_science_visual_staged_population,
)

SCIENCE_VISUAL_EXPANSION_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.3"
)


def science_visual_expansion_campaign_id(
    plan: LocalImageScienceCorpusVisualPilotPlanV3,
    predecessor_plans: tuple[ImageEvaluationArtifactMember, ...],
) -> str:
    body = {
        name: getattr(plan, name)
        for name in (
            "corpus_id",
            "corpus_manifest_sha256",
            "acquisition_sha256",
            "resolution_sha256",
            "resolution_policy_id",
            "resolution_policy_sha256",
            "selection_seed_sha256",
            "campaign_shard_count",
        )
    }
    body["predecessor_plans"] = tuple(
        pointer.model_dump(mode="json") for pointer in predecessor_plans
    )
    return "imgsciviscampaign_" + content_sha256(body)[7:39]


class LocalImageScienceCorpusVisualPilotPlanV4(LocalImageScienceCorpusVisualPilotPlanV3):
    schema_version: Literal["local-image-science-corpus-visual-pilot-plan/1.3"]  # type: ignore[assignment]
    selection_algorithm: Literal["SCIENCE_VISUAL_FROZEN_SOURCE_EXPANSION_V1"]  # type: ignore[assignment]
    predecessor_plans: tuple[ImageEvaluationArtifactMember, ...] = Field(min_length=2, max_length=4)
    campaign_shard_count: int = Field(ge=2, le=4)
    selected_sources: tuple[ScienceVisualPilotSource, ...] = Field(min_length=18, max_length=96)

    @model_validator(mode="after")
    def campaign_coordinates_are_coherent(self) -> Self:
        if self.campaign_shard_index >= self.campaign_shard_count:
            raise ValueError("science visual expansion shard index is invalid")
        count = len(self.selected_sources)
        if count % 6 or Counter(source.partition for source in self.selected_sources) != {
            "TRAIN": count * 2 // 3,
            "VALIDATION": count // 6,
            "HOLDOUT": count // 6,
        }:
            raise ValueError("science visual expansion partition quotas differ")
        if len(set(self.predecessor_plans)) != len(self.predecessor_plans) or any(
            pointer.schema_ref
            != "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.2"
            or pointer.media_type != "application/json"
            or pointer.member_path != "manifests/visual-pilot-plan.json"
            for pointer in self.predecessor_plans
        ):
            raise ValueError("science visual expansion predecessor pointers are invalid")
        if self.campaign_id != science_visual_expansion_campaign_id(self, self.predecessor_plans):
            raise ValueError("science visual expansion campaign ID differs")
        return self


class LocalImageScienceCorpusVisualPilotCommandV4(LocalImageScienceCorpusVisualPilotCommandV3):
    schema_version: Literal["local-image-science-corpus-visual-pilot-command/1.3"]  # type: ignore[assignment]
    staged_sources: tuple[ScienceVisualStagedSource, ...] = Field(min_length=18, max_length=96)

    @model_validator(mode="after")
    def immutable_command_is_coherent(self) -> Self:
        validate_science_visual_pilot_command_identity(
            self,
            plan=self.plan,
            plan_schema_ref=SCIENCE_VISUAL_EXPANSION_PLAN_SCHEMA_REF,
            staged_sources=self.staged_sources,
            attempt_id=self.attempt_id,
            command_sha256=self.command_sha256,
        )
        return self


def validate_science_visual_expansion_command(
    plan: LocalImageScienceCorpusVisualPilotPlanV4,
    command: LocalImageScienceCorpusVisualPilotCommandV4,
) -> None:
    if (
        type(plan) is not LocalImageScienceCorpusVisualPilotPlanV4
        or type(command) is not LocalImageScienceCorpusVisualPilotCommandV4
    ):
        raise ValueError("science visual expansion plan and command versions differ")
    validate_science_visual_staged_population(plan, command)
