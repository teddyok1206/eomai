"""Resolve and approve the exact past-exam source scope for local LoRA training.

The dominant access is one indexed Graph-revision lookup followed by ordered membership and bundle
joins.  Results are accumulated in maps/sets and sorted once, giving O(t + b) time and space for
target revisions and source bundles.  This application module returns a typed value and performs no
artifact or NAS write.
"""

from __future__ import annotations

from datetime import datetime

from eom_image_contracts import (
    ImageEvaluationSourceSnapshot,
    ImageTrainingRightsPolicy,
    LocalImageTrainingAuthorization,
    content_sha256,
    validate_contract,
)
from sqlalchemy import Engine, text


class LocalImageTrainingAuthorizationError(RuntimeError):
    """Stable fail-closed authorization-source error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_training_authorization_scope(
    engine: Engine,
    *,
    graph_revision_id: str,
    expected_graph_snapshot_sha256: str,
    expected_graph_manifest_sha256: str,
    expected_target_count: int,
) -> tuple[ImageEvaluationSourceSnapshot, tuple[ImageTrainingRightsPolicy, ...]]:
    """Read the exact accepted V9 target and rights-policy sets under one snapshot."""

    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        graph = (
            connection.execute(
                text(
                    """
                SELECT snapshot_sha256, manifest_sha256, state
                FROM knowledge_graph_snapshots
                WHERE graph_snapshot_revision_id = :graph_revision_id
                """
                ),
                {"graph_revision_id": graph_revision_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            graph is None
            or graph["state"] != "PUBLISHED"
            or graph["snapshot_sha256"] != expected_graph_snapshot_sha256
            or graph["manifest_sha256"] != expected_graph_manifest_sha256
        ):
            raise LocalImageTrainingAuthorizationError("IMAGE_TRAINING_GRAPH_SCOPE_INVALID")

        rows = connection.execute(
            text(
                """
                SELECT
                    r.item_revision_id,
                    b.assessment_source_bundle_revision_id,
                    b.rights_policy_id,
                    b.rights_policy_revision_id,
                    b.rights_policy_sha256
                FROM knowledge_snapshot_analyses s
                JOIN knowledge_analysis_runs r ON r.analysis_run_id = s.analysis_run_id
                JOIN assessment_source_bundle_revisions b
                  ON b.assessment_source_bundle_revision_id =
                    r.canonical_request->'source'->'bundle'->>
                      'assessment_source_bundle_revision_id'
                WHERE s.graph_snapshot_revision_id = :graph_revision_id
                  AND r.canonical_request->>'schema_version' =
                    'knowledge-analysis-request/9.0'
                  AND r.canonical_request->'source'->>'source_class' = 'PAST_EXAM'
                  AND r.state = 'ACCEPTED'
                  AND b.state IN ('REVIEWED','SUPERSEDED')
                ORDER BY r.item_revision_id, b.assessment_source_bundle_revision_id
                """
            ),
            {"graph_revision_id": graph_revision_id},
        ).mappings()
        target_ids: set[str] = set()
        bundle_ids: set[str] = set()
        policies: dict[str, ImageTrainingRightsPolicy] = {}
        for row in rows:
            item_revision_id = row["item_revision_id"]
            if not isinstance(item_revision_id, str):
                raise LocalImageTrainingAuthorizationError("IMAGE_TRAINING_TARGET_SCOPE_INVALID")
            target_ids.add(item_revision_id)
            bundle_ids.add(row["assessment_source_bundle_revision_id"])
            policy = ImageTrainingRightsPolicy.model_validate(
                {
                    "rights_policy_id": row["rights_policy_id"],
                    "rights_policy_revision_id": row["rights_policy_revision_id"],
                    "rights_policy_sha256": row["rights_policy_sha256"],
                }
            )
            prior = policies.get(policy.rights_policy_revision_id)
            if prior is not None and prior != policy:
                raise LocalImageTrainingAuthorizationError("IMAGE_TRAINING_RIGHTS_POLICY_CONFLICT")
            policies[policy.rights_policy_revision_id] = policy

    ordered_targets = tuple(sorted(target_ids))
    ordered_policies = tuple(policies[key] for key in sorted(policies))
    if (
        len(ordered_targets) != expected_target_count
        or not ordered_policies
        or len(bundle_ids) != len(ordered_policies)
    ):
        raise LocalImageTrainingAuthorizationError("IMAGE_TRAINING_SOURCE_SET_INCOMPLETE")
    return (
        ImageEvaluationSourceSnapshot(
            graph_revision_id=graph_revision_id,
            graph_snapshot_sha256=expected_graph_snapshot_sha256,
            graph_manifest_sha256=expected_graph_manifest_sha256,
            target_count=len(ordered_targets),
            target_set_sha256=content_sha256(ordered_targets),
        ),
        ordered_policies,
    )


def build_training_authorization(
    *,
    source_snapshot: ImageEvaluationSourceSnapshot,
    rights_policies: tuple[ImageTrainingRightsPolicy, ...],
    approved_at: datetime,
    approved_by: str,
) -> LocalImageTrainingAuthorization:
    """Create revision one of the bounded internal-adapter authorization."""

    scope_hash = content_sha256(
        {
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "rights_policies": [value.model_dump(mode="json") for value in rights_policies],
            "permitted_use": "INTERNAL_LORA_TRAINING",
            "derivative_output": "LORA_ADAPTER_ONLY",
        }
    ).removeprefix("sha256:")
    revision_hash = content_sha256(
        {
            "scope_hash": "sha256:" + scope_hash,
            "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
            "approved_by": approved_by,
        }
    ).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-training-authorization/1.0",
        "authorization_id": "imgtrainauth_" + scope_hash[:32],
        "authorization_revision_id": "imgtrainauthrev_" + revision_hash[:32],
        "revision_number": 1,
        "previous_revision_id": None,
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "rights_policies": [value.model_dump(mode="json") for value in rights_policies],
        "permitted_use": "INTERNAL_LORA_TRAINING",
        "derivative_output": "LORA_ADAPTER_ONLY",
        "state": "APPROVED",
        "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
        "approved_by": approved_by,
    }
    value = {**body, "authorization_sha256": content_sha256(body)}
    try:
        validate_contract("training-authorization", value)
        return LocalImageTrainingAuthorization.model_validate(value)
    except ValueError as exc:
        raise LocalImageTrainingAuthorizationError("IMAGE_TRAINING_AUTHORIZATION_INVALID") from exc
