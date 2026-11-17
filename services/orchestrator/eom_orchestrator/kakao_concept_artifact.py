"""Numeric textbook crop results at the Artifact byte boundary, not control messages."""

from pathlib import Path
from typing import TYPE_CHECKING

from eom_orchestrator.artifacts import StagedArtifact, stage_serialized_artifact

if TYPE_CHECKING:
    from eom_workflow.kakao_concept_result import KakaoConceptRoleResult


def stage_kakao_concept_artifact(
    *,
    result: "KakaoConceptRoleResult",
    staging: Path,
    worker_slot: str,
) -> StagedArtifact:
    # Lazy optional purpose dependency; ordinary jobs do not load the Kakao runtime.
    from eom_kakao_archive_contracts import canonical_bytes
    from eom_workflow.kakao_concept_result import KakaoConceptRoleResult

    checked = KakaoConceptRoleResult.model_validate(result.model_dump(mode="json"))
    return stage_serialized_artifact(
        result_bytes=canonical_bytes(checked.model_dump(mode="json")),
        job_id=checked.job_id,
        logical_artifact_id=checked.artifact.logical_artifact_id,
        revision_id=checked.artifact.revision_id,
        staging=staging,
        worker_slot=worker_slot,
    )
