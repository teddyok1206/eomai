"""Canonical saved-ranking bytes through the existing Orchestrator commit owner."""

from __future__ import annotations

import tempfile
from pathlib import Path

from eom_catalog_contracts.completed_public_ranking import CompletedPublicSimilarityRanking
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.state_machine import JobState

SAVED_PUBLIC_RANKING_ARTIFACT_TYPE = "control_completed_public_ranking"
SAVED_PUBLIC_RANKING_SCHEMA_REF = "eom://schemas/knowledge/completed-public-similarity-ranking/1.0"


class CompletedPublicRankingArtifactStore:
    """No source grants or model calls. Original publisher owns identity, locking and replay."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        self.publisher, self.source_commit = publisher, source_commit

    def find(self, key: str) -> ArtifactMemberPointer | None:
        try:
            return self.publisher.find_published_primary_member(
                idempotency_key=key,
                artifact_type=SAVED_PUBLIC_RANKING_ARTIFACT_TYPE,
            )
        except ControlPlaneError as error:
            if error.code != "CONTROL_FILE_SET_INCOMPLETE" or self.publisher.publication_state(
                idempotency_key=key,
                artifact_type=SAVED_PUBLIC_RANKING_ARTIFACT_TYPE,
            ) not in {
                JobState.CREATED,
                JobState.VALIDATED,
                JobState.QUEUED,
                JobState.CLAIMED,
                JobState.RUNNING,
                JobState.VALIDATING_RESULT,
                JobState.COMMITTING,
            }:
                raise
            # Recreate the same deterministic validated bytes and replay this key.
            # FAILED/SUCCEEDED-but-revoked/corrupt publications are never rewritten.
            return None

    def commit(self, value: CompletedPublicSimilarityRanking, key: str) -> ArtifactMemberPointer:
        checked = CompletedPublicSimilarityRanking.model_validate(value.model_dump(mode="json"))
        raw = canonical_json_bytes(checked.model_dump(mode="json"))
        with tempfile.TemporaryDirectory(
            prefix="saved-ranking-", dir=self.publisher.settings.workspace_root
        ) as directory:
            source = Path(directory) / "ranking.json"
            source.write_bytes(raw)
            source.chmod(0o600)
            published = self.publisher.publish_first_observation(
                members=(
                    ControlFileSetMember(
                        "ranking.json",
                        source,
                        sha256_bytes(raw),
                        len(raw),
                        SAVED_PUBLIC_RANKING_SCHEMA_REF,
                        "application/json",
                    ),
                ),
                primary_file="ranking.json",
                artifact_type=SAVED_PUBLIC_RANKING_ARTIFACT_TYPE,
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
                idempotency_key=key,
                source_commit=self.source_commit,
            )
        if published.primary_file != "ranking.json" or published.primary_sha256 != sha256_bytes(
            raw
        ):
            raise ValueError("COMPLETED_PUBLIC_RANKING_PUBLICATION_INVALID")
        return ArtifactMemberPointer(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            member_path="ranking.json",
            schema_ref=SAVED_PUBLIC_RANKING_SCHEMA_REF,
            media_type="application/json",
            sha256=published.primary_sha256,
        )
