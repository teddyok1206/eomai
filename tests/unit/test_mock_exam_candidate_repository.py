from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import (
    build_mock_exam_assembly_cohort,
    load_integrated_science_mock_exam_policy,
)
from eom_catalog_contracts.item_review import (
    MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
    MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF,
    MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA_REF,
    MockExamItemReviewDecisionV1,
    MockExamItemReviewDecisionV2,
    mock_exam_item_review_decision_sha256,
)
from eom_catalog_service.mock_exam_candidate_repository import (
    MockExamCandidateRepository,
    MockExamCandidateResolutionError,
)
from eom_catalog_service.models import ItemReviewRecord, ItemRevisionRecord
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy.dialects import postgresql


def _artifact_fixture(
    root: Path,
    *,
    payload: bytes = b"{}",
) -> tuple[MockExamCandidateRepository, ArtifactRecord, ArtifactRevisionRecord, Path]:
    artifact_id = "artifact_" + "1" * 32
    revision_id = "rev_" + "2" * 32
    job_id = "job_" + "3" * 32
    digest = sha256_bytes(payload)
    storage = root / artifact_id / revision_id
    storage.mkdir(parents=True)
    member = storage / "member.json"
    member.write_bytes(payload)
    manifest = {
        "logical_artifact_id": artifact_id,
        "revision_id": revision_id,
        "primary_file": "member.json",
        "files": [
            {
                "file_name": "member.json",
                "bytes": len(payload),
                "sha256": digest,
                "media_type": "application/json",
                "schema_ref": "eom://schemas/test/1.0",
            }
        ],
    }
    artifact = ArtifactRecord(
        logical_artifact_id=artifact_id,
        job_id=job_id,
        artifact_type="test-evidence",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=digest,
        manifest_hash=content_sha256(manifest),
        content_bytes=len(payload),
        nas_path=str(storage),
        manifest=manifest,
        result={},
        approved=True,
    )
    return (
        MockExamCandidateRepository(CatalogSettings(nas_artifact_root=root)),
        artifact,
        revision,
        member,
    )


def _read(
    repository: MockExamCandidateRepository,
    artifact: ArtifactRecord,
    revision: ArtifactRevisionRecord,
) -> bytes:
    return repository._read_member(
        artifact,
        revision,
        artifact_id=artifact.logical_artifact_id,
        revision_id=revision.revision_id,
        artifact_type="test-evidence",
        member_path="member.json",
        expected_sha256=revision.content_hash,
        max_bytes=1024,
        expected_media_type="application/json",
        expected_schema_ref="eom://schemas/test/1.0",
    )


class _CapturedRows:
    @staticmethod
    def all() -> list[Any]:
        return []


class _StatementCaptureSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> _CapturedRows:
        self.statements.append(statement)
        return _CapturedRows()


def test_exact_cohort_structural_lookup_is_one_bounded_indexed_query() -> None:
    revision_ids = tuple("itemrev_" + f"{index:032x}" for index in range(1, 26))
    cohort = build_mock_exam_assembly_cohort(revision_ids)
    session = _StatementCaptureSession()
    repository = MockExamCandidateRepository(CatalogSettings(nas_artifact_root=Path("/tmp")))

    rows = repository._structural_candidates(
        session,  # type: ignore[arg-type]
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        policy=load_integrated_science_mock_exam_policy(),
        cohort_revision_ids=tuple(member.item_revision_id for member in cohort.members),
    )

    assert rows == ()
    assert len(session.statements) == 1
    statement = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "item_revisions.item_revision_id IN (" in statement
    assert "LIMIT 26" in statement
    assert all(item_revision_id in statement for item_revision_id in revision_ids)
    assert ItemRevisionRecord.__table__.c.item_revision_id.primary_key


def test_candidate_member_resolution_is_hash_pinned_and_same_file_descriptor(
    tmp_path: Path,
) -> None:
    repository, artifact, revision, _member = _artifact_fixture(tmp_path)

    assert _read(repository, artifact, revision) == b"{}"


@pytest.mark.parametrize("failure", ["missing", "stale", "hash", "duplicate", "symlink"])
def test_candidate_member_resolution_rejects_invalid_or_ambiguous_pointers(
    tmp_path: Path,
    failure: str,
) -> None:
    repository, artifact, revision, member = _artifact_fixture(tmp_path)
    if failure == "missing":
        artifact.approved = False
    elif failure == "stale":
        revision.logical_artifact_id = "artifact_" + "4" * 32
    elif failure == "hash":
        member.write_bytes(b"[]")
    elif failure == "duplicate":
        revision.manifest = {
            **revision.manifest,
            "files": [*revision.manifest["files"], *revision.manifest["files"]],
        }
        revision.manifest_hash = content_sha256(revision.manifest)
    else:
        target = tmp_path / "untrusted.json"
        target.write_bytes(b"{}")
        member.unlink()
        member.symlink_to(target)

    with pytest.raises(MockExamCandidateResolutionError):
        _read(repository, artifact, revision)


@pytest.mark.parametrize(
    ("decision_version", "review_result_schema", "schema_ref", "require_v2"),
    (
        (
            "mock-exam-item-review-decision/1.0",
            "review-result@8.0",
            MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF,
            False,
        ),
        (
            "mock-exam-item-review-decision/2.0",
            "review-result@9.0",
            MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA_REF,
            True,
        ),
    ),
)
def test_candidate_review_pointer_requires_the_exact_content_family_decision(
    tmp_path: Path,
    decision_version: str,
    review_result_schema: str,
    schema_ref: str,
    require_v2: bool,
) -> None:
    artifact_id = "artifact_" + "a" * 32
    revision_id = "rev_" + "b" * 32
    job_id = "job_" + "c" * 32
    review_id = "itemreview_" + "d" * 32
    item_revision_id = "itemrev_" + "e" * 32
    workflow_id = "workflow_" + "f" * 32
    approved_at = datetime(2026, 9, 8, 6, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    unsigned = {
        "schema_version": decision_version,
        "item_review_record_id": review_id,
        "item_revision_id": item_revision_id,
        "workflow_id": workflow_id,
        "source_review": {
            "step_run_id": "steprun_" + "1" * 32,
            "artifact_id": "artifact_" + "2" * 32,
            "artifact_revision_id": "rev_" + "3" * 32,
            "sha256": "sha256:" + "4" * 64,
            "result_schema": review_result_schema,
            "worker_decision": "ready_for_human",
            "finding_counts": {"info": 0, "warning": 1, "blocking": 0},
        },
        "human_approval": {
            "approval_request_id": "approval_" + "5" * 32,
            "reviewer_operator_id": "operator_" + "6" * 32,
            "approved_at": approved_at,
        },
        "decision": "APPROVE",
        "final_rating": "C",
        "rating_policy_key": "integrated-science-item-rating",
        "rating_policy_revision_id": "ratingpolicyrev_" + "7" * 32,
        "rating_policy_sha256": "sha256:" + "8" * 64,
        "idempotency_key_sha256": "sha256:" + "9" * 64,
        "decided_at": approved_at,
    }
    decision_value = {
        **unsigned,
        "decision_sha256": mock_exam_item_review_decision_sha256(unsigned),
    }
    decision: MockExamItemReviewDecisionV1 = (
        MockExamItemReviewDecisionV2.model_validate(decision_value)
        if require_v2
        else MockExamItemReviewDecisionV1.model_validate(decision_value)
    )
    payload = canonical_json_bytes(decision)
    payload_sha256 = sha256_bytes(payload)
    storage = tmp_path / artifact_id / revision_id
    storage.mkdir(parents=True)
    (storage / MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME).write_bytes(payload)
    manifest = {
        "job_id": job_id,
        "logical_artifact_id": artifact_id,
        "revision_id": revision_id,
        "artifact_type": "mock-exam-item-review-decision",
        "primary_file": MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
        "content_hash": payload_sha256,
        "content_bytes": len(payload),
        "files": [
            {
                "file_name": MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
                "bytes": len(payload),
                "sha256": payload_sha256,
                "media_type": "application/json",
                "schema_ref": schema_ref,
            }
        ],
    }
    artifact = ArtifactRecord(
        logical_artifact_id=artifact_id,
        job_id=job_id,
        artifact_type="mock-exam-item-review-decision",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=payload_sha256,
        manifest_hash=content_sha256(manifest),
        content_bytes=len(payload),
        nas_path=str(storage),
        manifest=manifest,
        result={},
        approved=True,
    )
    summary = {
        "schema_version": "mock-exam-item-review-severity-summary/1.0",
        "final_rating": "C",
        "finding_counts": {"info": 0, "warning": 1, "blocking": 0},
        "rating_policy_revision_id": decision.rating_policy_revision_id,
        "rating_policy_sha256": decision.rating_policy_sha256,
        "review_result_schema": decision.source_review.result_schema,
        "review_step_run_id": decision.source_review.step_run_id,
        "source_review_artifact_id": decision.source_review.artifact_id,
        "source_review_artifact_revision_id": decision.source_review.artifact_revision_id,
        "source_review_sha256": decision.source_review.sha256,
        "human_approval_request_id": decision.human_approval.approval_request_id,
        "decision_sha256": decision.decision_sha256,
        "idempotency_key_sha256": decision.idempotency_key_sha256,
    }
    review = ItemReviewRecord(
        item_review_record_id=review_id,
        item_revision_id=item_revision_id,
        workflow_id=workflow_id,
        review_artifact_id=artifact_id,
        review_artifact_revision_id=revision_id,
        review_sha256=payload_sha256,
        decision="APPROVE",
        severity_summary=summary,
        reviewer_actor_id=decision.human_approval.reviewer_operator_id,
    )
    repository = MockExamCandidateRepository(CatalogSettings(nas_artifact_root=tmp_path))
    repository._validate_review_pointer(
        review,
        artifacts={artifact_id: artifact},
        revisions={revision_id: revision},
        require_v2=require_v2,
    )

    with pytest.raises(MockExamCandidateResolutionError) as mixed_family:
        repository._validate_review_pointer(
            review,
            artifacts={artifact_id: artifact},
            revisions={revision_id: revision},
            require_v2=not require_v2,
        )
    assert mixed_family.value.code == "ASSEMBLY_ARTIFACT_MANIFEST_INVALID"

    review.severity_summary = {**summary, "final_rating": "A"}
    with pytest.raises(MockExamCandidateResolutionError) as raised:
        repository._validate_review_pointer(
            review,
            artifacts={artifact_id: artifact},
            revisions={revision_id: revision},
            require_v2=require_v2,
        )
    assert raised.value.code == "ASSEMBLY_REVIEW_POINTER_INVALID"
