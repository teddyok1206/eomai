"""Build the bounded successor plan for raster-subject seed variance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceVisualSubjectMultiseedPlan,
    ScienceVisualSubjectMultiseedCase,
    content_sha256,
    science_subject_multiseed_value,
    validate_science_visual_subject_multiseed_plan,
)


def build_science_visual_subject_multiseed_plan(
    *,
    inventory: LocalImageScienceVisualSubjectInventory,
    initial_plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    initial_plan_pointer: ImageEvaluationArtifactMember,
    initial_review: LocalImageScienceVisualSubjectBenchmarkReview,
    initial_review_pointer: ImageEvaluationArtifactMember,
    created_at: datetime,
    created_by: str,
) -> LocalImageScienceVisualSubjectMultiseedPlan:
    """Create two additional fixed-seed cases for every reviewed raster subject."""

    if (
        initial_plan.subject_inventory != initial_review.subject_inventory
        or initial_review.benchmark_plan != initial_plan_pointer
    ):
        raise ValueError("science subject multi-seed predecessor pointer mismatch")
    subjects = {value.subject_id: value for value in inventory.subjects}
    initial_cases = {
        value.subject_id: value for value in initial_plan.cases if value.case_kind == "QUALITY"
    }
    reviewed = {
        value.subject_id: value
        for value in initial_review.reviews
        if value.render_route in {"HYBRID", "LORA_RASTER"}
    }
    if set(initial_cases) != set(reviewed):
        raise ValueError("science subject multi-seed predecessor coverage mismatch")
    cases: list[ScienceVisualSubjectMultiseedCase] = []
    for subject_id in sorted(reviewed, key=lambda value: subjects[value].subject_key):
        subject = subjects[subject_id]
        original = initial_cases[subject_id]
        if (
            subject.raster_prompt_en is None
            or subject.raster_prompt_sha256 is None
            or original.negative_prompt_en is None
            or original.negative_prompt_sha256 is None
        ):
            raise ValueError("science subject multi-seed prompt source is missing")
        for ordinal in (1, 2):
            seed = science_subject_multiseed_value(subject.subject_key, ordinal)
            identity = content_sha256(
                {
                    "seed": seed,
                    "seed_ordinal": ordinal,
                    "subject_id": subject.subject_id,
                }
            ).removeprefix("sha256:")[:32]
            cases.append(
                ScienceVisualSubjectMultiseedCase(
                    case_id=f"imgscisubjectseedcase_{identity}",
                    subject_id=subject.subject_id,
                    subject_key=subject.subject_key,
                    render_route=cast(Literal["HYBRID", "LORA_RASTER"], subject.render_route),
                    seed_ordinal=ordinal,
                    seed=seed,
                    prompt_en=subject.raster_prompt_en,
                    prompt_sha256=subject.raster_prompt_sha256,
                    negative_prompt_en=original.negative_prompt_en,
                    negative_prompt_sha256=original.negative_prompt_sha256,
                )
            )
    base = {
        "schema_version": "local-image-science-visual-subject-multiseed-plan/1.0",
        "subject_inventory": initial_plan.subject_inventory.model_dump(mode="json"),
        "initial_benchmark_plan": initial_plan_pointer.model_dump(mode="json"),
        "initial_quality_review": initial_review_pointer.model_dump(mode="json"),
        "base_model": initial_plan.base_model.model_dump(mode="json"),
        "adapter_manifest": initial_plan.adapter_manifest.model_dump(mode="json"),
        "generation_width_px": initial_plan.generation_width_px,
        "generation_height_px": initial_plan.generation_height_px,
        "delivery_width_px": initial_plan.delivery_width_px,
        "delivery_height_px": initial_plan.delivery_height_px,
        "inference_steps": initial_plan.inference_steps,
        "guidance_scale_milli": initial_plan.guidance_scale_milli,
        "seeds_per_subject": 2,
        "cases": tuple(
            value.model_dump(mode="json") for value in sorted(cases, key=lambda item: item.case_id)
        ),
        "activation_policy": "FORBIDDEN",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    identity = content_sha256(
        {key: value for key, value in base.items() if key not in {"created_at", "created_by"}}
    ).removeprefix("sha256:")[:32]
    with_id = {**base, "plan_id": f"imgscisubjectmultiseed_{identity}"}
    plan = LocalImageScienceVisualSubjectMultiseedPlan.model_validate(
        {**with_id, "plan_sha256": content_sha256(with_id)}
    )
    validate_science_visual_subject_multiseed_plan(
        inventory,
        initial_plan,
        initial_review,
        plan,
    )
    return plan
