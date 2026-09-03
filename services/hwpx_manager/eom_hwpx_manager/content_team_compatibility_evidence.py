"""Resolve exact successful HwpQuestionEditor builds as compatibility evidence."""

from __future__ import annotations

from eom_catalog_contracts import HwpQuestionEditorProfilePointer
from eom_hwpx_contracts import CONTENT_TEAM_HANDOFF_MEMBERS, ContentTeamHandoffSnapshot
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy import Engine, select

from eom_hwpx_manager.models import HwpxApplicationBuildRecord


class ExistingContentTeamBuildEvidenceResolver:
    """Return evidence only for an approved output from the exact immutable input tuple."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def resolve(
        self,
        *,
        item_revision_id: str,
        item_content_sha256: str,
        renderer_profile: HwpQuestionEditorProfilePointer,
    ) -> str | None:
        snapshot = ContentTeamHandoffSnapshot.model_validate(
            {
                "artifact_id": renderer_profile.artifact_id,
                "artifact_revision_id": renderer_profile.artifact_revision_id,
                "archive_sha256": renderer_profile.archive_sha256,
                "profile_sha256": renderer_profile.profile_sha256,
                "members": [
                    {"purpose": purpose, "sha256": sha256, "size": size}
                    for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
                ],
            }
        )
        expected_handoff = snapshot.model_dump(mode="json")
        with self.sessions() as session:
            candidates = tuple(
                session.scalars(
                    select(HwpxApplicationBuildRecord)
                    .where(
                        HwpxApplicationBuildRecord.item_revision_id == item_revision_id,
                        HwpxApplicationBuildRecord.source_sha256 == item_content_sha256,
                        HwpxApplicationBuildRecord.renderer == "content-team",
                        HwpxApplicationBuildRecord.renderer_version == "1.0.0",
                        HwpxApplicationBuildRecord.state == "SUCCEEDED",
                        HwpxApplicationBuildRecord.validation_state == "PASS",
                    )
                    .order_by(
                        HwpxApplicationBuildRecord.completed_at.desc(),
                        HwpxApplicationBuildRecord.build_id.desc(),
                    )
                )
            )
            matching = [
                build
                for build in candidates
                if build.options.get("handoff") == expected_handoff
                and build.output_artifact_id is not None
                and build.output_artifact_revision_id is not None
                and build.output_sha256 is not None
            ]
            if not matching:
                return None
            build = matching[0]
            artifact = session.get(ArtifactRecord, build.output_artifact_id)
            revision = session.get(ArtifactRevisionRecord, build.output_artifact_revision_id)
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
                or revision.logical_artifact_id != build.output_artifact_id
                or revision.content_hash != build.output_sha256
                or revision.job_id != build.platform_job_id
            ):
                return None
            return content_sha256(
                {
                    "validator": "content-team.hwp-question-editor-build",
                    "validator_revision": "1.0",
                    "build_id": build.build_id,
                    "item_revision_id": build.item_revision_id,
                    "source_artifact_id": build.source_artifact_id,
                    "source_artifact_revision_id": build.source_artifact_revision_id,
                    "source_sha256": build.source_sha256,
                    "renderer_profile": expected_handoff,
                    "output_artifact_id": build.output_artifact_id,
                    "output_artifact_revision_id": build.output_artifact_revision_id,
                    "output_sha256": build.output_sha256,
                    "validation_state": build.validation_state,
                }
            )
