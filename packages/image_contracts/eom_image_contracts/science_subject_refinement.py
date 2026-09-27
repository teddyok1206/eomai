"""Per-subject refinement decisions derived from immutable multi-seed evidence."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.science_subject_benchmark import (
    SUBJECT_INVENTORY_SCHEMA_REF,
    LocalImageScienceVisualSubjectInventory,
)
from eom_image_contracts.science_subject_multiseed import (
    SUBJECT_MULTISEED_REVIEW_SCHEMA_REF,
    LocalImageScienceVisualSubjectMultiseedReview,
    ScienceVisualMultiseedNextAction,
    ScienceVisualMultiseedStability,
    ScienceVisualRasterRoute,
)

SUBJECT_REFINEMENT_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-refinement-plan/1.0"
)

ScienceVisualSubjectProductionDisposition = Literal["BASE_ONLY", "BLOCK_UNTIL_REFINED"]
ScienceVisualSubjectCandidateRoute = Literal["HYBRID", "LORA_RASTER", "PYTHON_SVG"]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _safe_ascii(value: str) -> str:
    if (
        value != value.strip()
        or value != unicodedata.normalize("NFC", value)
        or not value.isascii()
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError("candidate prompt must be trimmed printable ASCII")
    return value


def _require_pointer(
    pointer: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    member_path: str,
) -> None:
    if (
        pointer.schema_ref != schema_ref
        or pointer.member_path != member_path
        or pointer.media_type != "application/json"
    ):
        raise ValueError("science subject refinement pointer contract mismatch")


class ScienceVisualSubjectRefinementStrategy(FrozenModel):
    """One content-bound decision for a reviewed raster subject."""

    subject_id: str = Field(pattern=r"^imgscisubject_[0-9a-f]{32}$")
    subject_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    source_render_route: ScienceVisualRasterRoute
    source_stability: ScienceVisualMultiseedStability
    evidence_case_ids: tuple[str, ...] = Field(min_length=3, max_length=3)
    production_disposition: ScienceVisualSubjectProductionDisposition
    research_actions: tuple[ScienceVisualMultiseedNextAction, ...] = Field(max_length=8)
    candidate_route: ScienceVisualSubjectCandidateRoute
    candidate_prompt_en: str | None = Field(default=None, min_length=20, max_length=2000)
    candidate_prompt_sha256: Sha256 | None

    @field_validator("evidence_case_ids")
    @classmethod
    def valid_evidence_case_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(
            not case_id.startswith(("imgscisubjectcase_", "imgscisubjectseedcase_"))
            or len(case_id.rsplit("_", 1)[-1]) != 32
            for case_id in value
        ):
            raise ValueError("refinement evidence cases must be uniquely sorted subject cases")
        return value

    @field_validator("candidate_prompt_en")
    @classmethod
    def safe_candidate_prompt(cls, value: str | None) -> str | None:
        return None if value is None else _safe_ascii(value)

    @model_validator(mode="after")
    def coherent_strategy(self) -> Self:
        if self.research_actions != tuple(sorted(set(self.research_actions))):
            raise ValueError("refinement research actions must be uniquely sorted")
        prompt_required = "PROMPT_REFINEMENT" in self.research_actions
        if prompt_required != (self.candidate_prompt_en is not None):
            raise ValueError("prompt refinement must carry exactly one candidate prompt")
        expected_prompt_hash = (
            None if self.candidate_prompt_en is None else text_sha256(self.candidate_prompt_en)
        )
        if self.candidate_prompt_sha256 != expected_prompt_hash:
            raise ValueError("candidate prompt hash mismatch")
        route_review = "ROUTE_RECLASSIFICATION" in self.research_actions
        if route_review != (self.candidate_route == "PYTHON_SVG"):
            raise ValueError("route reclassification must target PYTHON_SVG")
        if not route_review and self.candidate_route != self.source_render_route:
            raise ValueError("non-reclassified subject must preserve its source route")
        if self.source_stability == "NEITHER_ACCEPTABLE":
            if self.production_disposition != "BLOCK_UNTIL_REFINED":
                raise ValueError("unacceptable subject must remain blocked until refined")
        elif self.production_disposition != "BASE_ONLY":
            raise ValueError("reviewed subject production must remain base-only")
        if ("ADAPTER_PRODUCTION_CANARY" in self.research_actions) != (
            self.source_stability == "STABLE_ADAPTER_PREFERRED"
        ):
            raise ValueError("adapter canary requires stable adapter preference")
        return self


class LocalImageScienceVisualSubjectRefinementPlan(FrozenModel):
    """Immutable refinement strategy over one exact multi-seed review population."""

    schema_version: Literal["local-image-science-visual-subject-refinement-plan/1.0"]
    plan_id: str = Field(pattern=r"^imgscisubjectrefinement_[0-9a-f]{32}$")
    subject_inventory: ImageEvaluationArtifactMember
    multiseed_review: ImageEvaluationArtifactMember
    strategies: tuple[ScienceVisualSubjectRefinementStrategy, ...] = Field(
        min_length=1, max_length=64
    )
    global_adapter_activation: Literal["FORBIDDEN"]
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def exact_plan_identity(self) -> Self:
        _require_pointer(
            self.subject_inventory,
            schema_ref=SUBJECT_INVENTORY_SCHEMA_REF,
            member_path="manifests/science-visual-subject-inventory.json",
        )
        _require_pointer(
            self.multiseed_review,
            schema_ref=SUBJECT_MULTISEED_REVIEW_SCHEMA_REF,
            member_path="manifests/science-visual-subject-multiseed-review.json",
        )
        keys = tuple(strategy.subject_key for strategy in self.strategies)
        ids = tuple(strategy.subject_id for strategy in self.strategies)
        if keys != tuple(sorted(set(keys))) or len(ids) != len(set(ids)):
            raise ValueError("refinement strategies must be uniquely sorted by subject key")
        identity = content_sha256(
            self.model_dump(
                mode="json",
                exclude={"plan_id", "created_at", "created_by", "plan_sha256"},
            )
        ).removeprefix("sha256:")[:32]
        if self.plan_id != f"imgscisubjectrefinement_{identity}":
            raise ValueError("science subject refinement plan ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("science subject refinement plan hash mismatch")
        return self


def build_science_visual_subject_refinement_plan(
    *,
    inventory: LocalImageScienceVisualSubjectInventory,
    inventory_pointer: ImageEvaluationArtifactMember,
    review: LocalImageScienceVisualSubjectMultiseedReview,
    review_pointer: ImageEvaluationArtifactMember,
    candidate_prompts: Mapping[str, str],
    created_at: datetime,
    created_by: str,
) -> LocalImageScienceVisualSubjectRefinementPlan:
    """Build one complete plan in O(S), rejecting missing or surplus prompt decisions."""

    _require_utc(created_at)
    prompt_subjects = {
        entry.subject_key for entry in review.reviews if "PROMPT_REFINEMENT" in entry.next_actions
    }
    if set(candidate_prompts) != prompt_subjects:
        raise ValueError("candidate prompt population does not match the review")
    strategies = tuple(
        ScienceVisualSubjectRefinementStrategy(
            subject_id=entry.subject_id,
            subject_key=entry.subject_key,
            source_render_route=entry.render_route,
            source_stability=entry.stability_status,
            evidence_case_ids=tuple(sorted(value.case_id for value in entry.evaluations)),
            production_disposition=(
                "BLOCK_UNTIL_REFINED"
                if entry.stability_status == "NEITHER_ACCEPTABLE"
                else "BASE_ONLY"
            ),
            research_actions=tuple(sorted(entry.next_actions)),
            candidate_route=(
                "PYTHON_SVG"
                if "ROUTE_RECLASSIFICATION" in entry.next_actions
                else entry.render_route
            ),
            candidate_prompt_en=candidate_prompts.get(entry.subject_key),
            candidate_prompt_sha256=(
                None
                if entry.subject_key not in candidate_prompts
                else text_sha256(candidate_prompts[entry.subject_key])
            ),
        )
        for entry in sorted(review.reviews, key=lambda value: value.subject_key)
    )
    identity_body = {
        "schema_version": "local-image-science-visual-subject-refinement-plan/1.0",
        "subject_inventory": inventory_pointer.model_dump(mode="json"),
        "multiseed_review": review_pointer.model_dump(mode="json"),
        "strategies": [value.model_dump(mode="json") for value in strategies],
        "global_adapter_activation": "FORBIDDEN",
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")[:32]
    body = {
        **identity_body,
        "plan_id": f"imgscisubjectrefinement_{identity}",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    plan = LocalImageScienceVisualSubjectRefinementPlan.model_validate(
        {**body, "plan_sha256": content_sha256(body)}
    )
    validate_science_visual_subject_refinement_plan(
        inventory,
        review,
        plan,
        inventory_pointer=inventory_pointer,
        review_pointer=review_pointer,
    )
    return plan


def validate_science_visual_subject_refinement_plan(
    inventory: LocalImageScienceVisualSubjectInventory,
    review: LocalImageScienceVisualSubjectMultiseedReview,
    plan: LocalImageScienceVisualSubjectRefinementPlan,
    *,
    inventory_pointer: ImageEvaluationArtifactMember,
    review_pointer: ImageEvaluationArtifactMember,
) -> None:
    """Close the exact subject/review/strategy population with indexed O(S + E) checks."""

    if plan.subject_inventory != inventory_pointer or plan.multiseed_review != review_pointer:
        raise ValueError("refinement plan predecessor pointer mismatch")
    subjects = {subject.subject_id: subject for subject in inventory.subjects}
    reviews = {entry.subject_id: entry for entry in review.reviews}
    strategies = {strategy.subject_id: strategy for strategy in plan.strategies}
    if set(strategies) != set(reviews):
        raise ValueError("refinement strategy population does not match the review")
    for subject_id, entry in reviews.items():
        subject = subjects.get(subject_id)
        strategy = strategies[subject_id]
        if (
            subject is None
            or subject.subject_key != entry.subject_key
            or subject.render_route != entry.render_route
            or strategy.subject_key != entry.subject_key
            or strategy.source_render_route != entry.render_route
            or strategy.source_stability != entry.stability_status
            or strategy.evidence_case_ids
            != tuple(sorted(value.case_id for value in entry.evaluations))
            or strategy.research_actions != tuple(sorted(entry.next_actions))
        ):
            raise ValueError("refinement strategy changes pinned subject or review evidence")
