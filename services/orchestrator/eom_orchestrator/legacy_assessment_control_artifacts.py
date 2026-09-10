"""Orchestrator-owned publication of canonical legacy-assessment control documents."""

from __future__ import annotations

import re
from datetime import datetime

from eom_catalog_contracts import (
    ArtifactMember,
    AssessmentArtifactMemberPointer,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionValidationRecovery,
    PdfLearningCompletionReceipt,
    PdfLearningItemCompletionShard,
    SourceRelease,
    completion_identity_sha256,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import ControlArtifactPointer

from eom_orchestrator.control_artifacts import ControlArtifactPublisher

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
COVERAGE_MEMBER = "coverage.json"
COVERAGE_SCHEMA_REF = "eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0"
RECOVERY_MEMBER = "validation-recovery.json"
RECOVERY_SCHEMA_REF = (
    "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0"
)
COVERAGE_ARTIFACT_TYPE = "control_legacy_item_corpus_coverage"
RECOVERY_ARTIFACT_TYPE = "control_legacy_item_extraction_validation_recovery"
COMPLETION_SHARD_ARTIFACT_TYPE = "control_pdf_learning_completion_shard"
COMPLETION_RECEIPT_ARTIFACT_TYPE = "control_pdf_learning_completion_receipt"
COMPLETION_SHARD_SCHEMA_REF = (
    "eom://schemas/legacy-assessment/pdf-learning-item-completion-shard/1.0"
)
COMPLETION_RECEIPT_SCHEMA_REF = "eom://schemas/legacy-assessment/pdf-learning-completion/1.0"
COMPLETION_RECEIPT_SCHEMA_REF_V2 = "eom://schemas/legacy-assessment/pdf-learning-completion/1.1"
COMPLETION_RECEIPT_SCHEMA_REF_V3 = "eom://schemas/legacy-assessment/pdf-learning-completion/1.2"


class LegacyAssessmentControlArtifactPublisher:
    """Adapt reviewed values to the sole NAS-writing Orchestrator boundary.

    ``source_commit`` must come from installed release metadata supplied by composition. This
    adapter never inspects Git or a source checkout at runtime.
    """

    def __init__(
        self,
        publisher: ControlArtifactPublisher,
        *,
        source_release: SourceRelease,
    ) -> None:
        if _COMMIT.fullmatch(source_release.git_commit) is None:
            raise ValueError("legacy assessment Artifact source commit is invalid")
        self.publisher = publisher
        self.source_release = source_release

    def commit_coverage(
        self,
        coverage: LegacyItemCorpusCoverage,
        *,
        idempotency_key: str,
    ) -> AssessmentArtifactMemberPointer:
        """Commit one canonical coverage member under its semantic content identity."""

        payload = canonical_json_bytes(coverage.model_dump(mode="json"))
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name=COVERAGE_MEMBER,
            schema_ref=COVERAGE_SCHEMA_REF,
            media_type="application/json",
            artifact_type=COVERAGE_ARTIFACT_TYPE,
            idempotency_key=idempotency_key,
            created_at=coverage.created_at,
            source_commit=self.source_release.git_commit,
        )
        return self._assessment_pointer(
            published.pointer,
            member=COVERAGE_MEMBER,
            schema_ref=COVERAGE_SCHEMA_REF,
            expected_sha256=sha256_bytes(payload),
        )

    def commit_recovery_authorization(
        self,
        recovery: LegacyItemExtractionValidationRecovery,
    ) -> AssessmentArtifactMemberPointer:
        """Commit the independently versioned recovery authority with its specified newline."""

        payload = canonical_json_bytes(recovery) + b"\n"
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name=RECOVERY_MEMBER,
            schema_ref=RECOVERY_SCHEMA_REF,
            media_type="application/json",
            artifact_type=RECOVERY_ARTIFACT_TYPE,
            idempotency_key=f"legacy-item-extraction-recovery:{recovery.recovery_sha256}",
            created_at=recovery.created_at,
            source_commit=self.source_release.git_commit,
        )
        return self._assessment_pointer(
            published.pointer,
            member=RECOVERY_MEMBER,
            schema_ref=RECOVERY_SCHEMA_REF,
            expected_sha256=sha256_bytes(payload),
        )

    def commit_completion_shard(
        self,
        shard: PdfLearningItemCompletionShard,
        *,
        completion_map_sha256: str,
        created_at: datetime,
    ) -> ArtifactMember:
        """Publish one deterministic <=64-chain component through the control boundary."""

        member = f"item-completions/shard-{shard.shard_index:02d}.json"
        document = shard.model_dump(mode="json")
        validate_contract("pdf-learning-item-completion-shard", document)
        payload = canonical_json_bytes(document)
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name=member,
            schema_ref=COMPLETION_SHARD_SCHEMA_REF,
            media_type="application/json",
            artifact_type=COMPLETION_SHARD_ARTIFACT_TYPE,
            idempotency_key=(
                "pdf-learning-shard:"
                + content_sha256(
                    {
                        "completion_map_sha256": completion_map_sha256,
                        "shard_index": shard.shard_index,
                        "shard_sha256": shard.shard_sha256,
                    }
                ).removeprefix("sha256:")
            ),
            created_at=created_at,
            source_commit=self.source_release.git_commit,
        )
        return ArtifactMember.model_validate(
            self._assessment_pointer(
                published.pointer,
                member=member,
                schema_ref=COMPLETION_SHARD_SCHEMA_REF,
                expected_sha256=sha256_bytes(payload),
            ).model_dump(mode="json")
        )

    def commit_completion_receipt(
        self,
        receipt: PdfLearningCompletionReceipt,
        *,
        completion_identity: str,
    ) -> ArtifactMember:
        """Publish the small header only after all nine shard pointers are final."""

        if receipt.source_release != self.source_release:
            raise ValueError("completion receipt source release differs from installed admission")
        if completion_identity != completion_identity_sha256(receipt):
            raise ValueError("completion receipt semantic identity differs")
        schema_route, schema_ref = {
            "eom-pdf-learning-completion/1.0": (
                "pdf-learning-completion",
                COMPLETION_RECEIPT_SCHEMA_REF,
            ),
            "eom-pdf-learning-completion/1.1": (
                "pdf-learning-completion-v2",
                COMPLETION_RECEIPT_SCHEMA_REF_V2,
            ),
            "eom-pdf-learning-completion/1.2": (
                "pdf-learning-completion-v3",
                COMPLETION_RECEIPT_SCHEMA_REF_V3,
            ),
        }[receipt.schema_version]
        member = "completion-receipt.json"
        document = receipt.model_dump(mode="json")
        validate_contract(schema_route, document)
        payload = canonical_json_bytes(document)
        published = self.publisher.publish_bytes(
            payload=payload,
            logical_name=member,
            schema_ref=schema_ref,
            media_type="application/json",
            artifact_type=COMPLETION_RECEIPT_ARTIFACT_TYPE,
            idempotency_key=(
                "pdf-learning-completion-receipt:" + completion_identity.removeprefix("sha256:")
            ),
            created_at=receipt.observed_at_utc,
            source_commit=self.source_release.git_commit,
        )
        return ArtifactMember.model_validate(
            self._assessment_pointer(
                published.pointer,
                member=member,
                schema_ref=schema_ref,
                expected_sha256=sha256_bytes(payload),
            ).model_dump(mode="json")
        )

    @staticmethod
    def _assessment_pointer(
        pointer: ControlArtifactPointer,
        *,
        member: str,
        schema_ref: str,
        expected_sha256: str,
    ) -> AssessmentArtifactMemberPointer:
        logical_name = pointer.logical_name
        if (
            logical_name != member
            or pointer.schema_ref != schema_ref
            or pointer.media_type != "application/json"
            or pointer.sha256 != expected_sha256
        ):
            raise ValueError("orchestrator returned a drifted legacy assessment Artifact pointer")
        return AssessmentArtifactMemberPointer(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=logical_name,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=expected_sha256,
        )


__all__ = [
    "COMPLETION_RECEIPT_ARTIFACT_TYPE",
    "COMPLETION_RECEIPT_SCHEMA_REF",
    "COMPLETION_RECEIPT_SCHEMA_REF_V2",
    "COMPLETION_RECEIPT_SCHEMA_REF_V3",
    "COMPLETION_SHARD_ARTIFACT_TYPE",
    "COMPLETION_SHARD_SCHEMA_REF",
    "COVERAGE_ARTIFACT_TYPE",
    "COVERAGE_MEMBER",
    "COVERAGE_SCHEMA_REF",
    "RECOVERY_ARTIFACT_TYPE",
    "RECOVERY_MEMBER",
    "RECOVERY_SCHEMA_REF",
    "LegacyAssessmentControlArtifactPublisher",
]
