"""Bind an existing holdout selection to the canonical training source snapshot."""

from __future__ import annotations

from datetime import datetime

from eom_image_contracts import (
    ImageEvaluationSourceSnapshot,
    LocalImageQualityEvaluationPlan,
    content_sha256,
    validate_contract,
)
from pydantic import ValidationError as PydanticValidationError


class TrainingEvaluationPlanError(RuntimeError):
    """Stable fail-closed evaluation-plan alignment error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def align_training_holdout_plan(
    *,
    template: LocalImageQualityEvaluationPlan,
    source_snapshot: ImageEvaluationSourceSnapshot,
    created_at: datetime,
) -> LocalImageQualityEvaluationPlan:
    """Create a successor plan without changing its ordered holdout samples or prompts."""

    current = template.source_snapshot
    if (
        current.graph_revision_id != source_snapshot.graph_revision_id
        or current.graph_snapshot_sha256 != source_snapshot.graph_snapshot_sha256
        or current.graph_manifest_sha256 != source_snapshot.graph_manifest_sha256
        or current.target_count != source_snapshot.target_count
    ):
        raise TrainingEvaluationPlanError("IMAGE_TRAINING_HOLDOUT_SOURCE_MISMATCH")
    sample_ids = tuple(value.sample_id for value in template.samples)
    anchor_ids = tuple(value.source_anchor_id for value in template.samples)
    if (
        len(sample_ids) != 12
        or len(sample_ids) != len(set(sample_ids))
        or len(anchor_ids) != len(set(anchor_ids))
    ):
        raise TrainingEvaluationPlanError("IMAGE_TRAINING_HOLDOUT_SET_INVALID")
    identity = content_sha256(
        {
            "predecessor_evaluation_id": template.evaluation_id,
            "predecessor_plan_sha256": template.plan_sha256,
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "sample_ids": sample_ids,
            "source_anchor_ids": tuple(sorted(anchor_ids)),
        }
    ).removeprefix("sha256:")
    body = template.model_dump(mode="json", exclude={"plan_sha256"})
    body.update(
        {
            "evaluation_id": "imageeval_" + identity[:32],
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "source_snapshot": source_snapshot.model_dump(mode="json"),
        }
    )
    value = {**body, "plan_sha256": content_sha256(body)}
    try:
        validate_contract("quality-evaluation-plan", value)
        return LocalImageQualityEvaluationPlan.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise TrainingEvaluationPlanError("IMAGE_TRAINING_HOLDOUT_PLAN_INVALID") from exc
