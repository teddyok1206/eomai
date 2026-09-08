"""Released, immutable inputs for the mock-exam production application use case.

This module resolves small policy/preset values only.  Item content, prompt text, artifacts, and
worker output never cross this boundary.
"""

from __future__ import annotations

from typing import Never, Protocol

from eom_api_contracts.control_plane import ExecutionPresetView
from eom_api_contracts.mock_exam_execution import (
    MockExamAnalysisPolicyPointerV1,
    MockExamGenerationBlockResolutionV1,
    MockExamRatingPolicyPointerV1,
)
from eom_catalog_contracts import (
    KnowledgeAnalysisRiskPolicy,
    build_integrated_science_mock_exam_production_plan_v2,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
)
from eom_catalog_contracts.mock_exam_production_plan import MockExamProductionPlanV2
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import (
    KnowledgeAnalysisRiskPolicyRevisionRecord,
)
from sqlalchemy import Engine

from eom_api.services.mock_exam_production_application import (
    MockExamAccessPolicyPointer,
)

RELEASED_ANALYSIS_POLICY_REVISION_ID = "analysisriskrev_7f0f1d7c2f7c4a3cb97c090938e8ac30"
RELEASED_ANALYSIS_POLICY_SHA256 = (
    "sha256:fa6efb2e77a3e639061317ca7d7617f072c01ecae807859f0222eaeccd208c0f"
)


class MockExamProductionReleaseError(RuntimeError):
    """Stable fail-closed error for a missing, stale, or mismatched release pointer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AnalysisPolicyPointerReader(Protocol):
    def resolve_analysis_policy(
        self,
        *,
        revision_id: str,
        expected_sha256: str,
    ) -> MockExamAnalysisPolicyPointerV1: ...


class ExecutionPresetReader(Protocol):
    def preset(self, preset_id: str) -> ExecutionPresetView: ...


class DatabaseAnalysisPolicyPointerReader:
    """Read one exact released risk policy; this adapter never writes or materializes artifacts."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = build_session_factory(engine)

    def resolve_analysis_policy(
        self,
        *,
        revision_id: str,
        expected_sha256: str,
    ) -> MockExamAnalysisPolicyPointerV1:
        with self._sessions() as session:
            record = session.get(KnowledgeAnalysisRiskPolicyRevisionRecord, revision_id)
        if record is None or record.state != "RELEASED":
            _fail(
                "PRODUCTION_ANALYSIS_POLICY_MISSING",
                "the pinned released analysis policy is unavailable",
            )
        try:
            policy = KnowledgeAnalysisRiskPolicy.model_validate(record.canonical_document)
        except ValueError as exc:
            raise MockExamProductionReleaseError(
                "PRODUCTION_ANALYSIS_POLICY_INVALID",
                "the pinned analysis policy failed canonical validation",
            ) from exc
        if (
            record.risk_policy_revision_id != revision_id
            or record.content_sha256 != expected_sha256
            or policy.risk_policy_revision_id != revision_id
            or policy.content_sha256 != expected_sha256
            or policy.state != "RELEASED"
        ):
            _fail(
                "PRODUCTION_ANALYSIS_POLICY_STALE",
                "the pinned analysis policy identity or hash differs",
            )
        return MockExamAnalysisPolicyPointerV1(
            risk_policy_revision_id=revision_id,
            risk_policy_sha256=expected_sha256,
        )


class ReleasedMockExamProductionResolver:
    """Cache packaged static inputs and re-resolve mutable storage pointers by exact revision."""

    def __init__(
        self,
        *,
        analysis_policies: AnalysisPolicyPointerReader,
        presets: ExecutionPresetReader,
    ) -> None:
        self._analysis_policies = analysis_policies
        self._presets = presets
        policy = load_integrated_science_mock_exam_policy()
        layout = load_integrated_science_mock_exam_layout_policy()
        outline = load_integrated_science_editorial_outline()
        self._plan = build_integrated_science_mock_exam_production_plan_v2(
            policy=policy,
            layout_policy=layout,
            outline=outline,
        )
        rating = load_integrated_science_mock_exam_rating_policy()
        if rating.state != "RELEASED":
            _fail(
                "PRODUCTION_RATING_POLICY_NOT_RELEASED",
                "the packaged mock-exam rating policy is not released",
            )
        self._rating_policy = MockExamRatingPolicyPointerV1(
            rating_policy_revision_id=rating.rating_policy_revision_id,
            rating_policy_sha256=content_sha256(rating.model_dump(mode="json")),
        )

    def production_plan(self) -> MockExamProductionPlanV2:
        """Return the frozen, self-hashed plan built only from packaged released inputs."""

        return self._plan

    def analysis_policy(self) -> MockExamAnalysisPolicyPointerV1:
        """Resolve the exact reviewed analysis policy; never select an implicit latest row."""

        return self._analysis_policies.resolve_analysis_policy(
            revision_id=RELEASED_ANALYSIS_POLICY_REVISION_ID,
            expected_sha256=RELEASED_ANALYSIS_POLICY_SHA256,
        )

    def rating_policy(self) -> MockExamRatingPolicyPointerV1:
        return self._rating_policy

    def access_policy(
        self,
        generation: MockExamGenerationBlockResolutionV1,
    ) -> MockExamAccessPolicyPointer:
        """Resolve access policy from the execution's immutable preset revision, not current."""

        preset = self._presets.preset(generation.execution_preset_id)
        revisions = {row.preset_revision_id: row for row in preset.revisions}
        revision = revisions.get(generation.execution_preset_revision_id)
        if (
            preset.preset_id != generation.execution_preset_id
            or preset.preset_key != generation.execution_preset_key
            or revision is None
            or revision.preset_id != preset.preset_id
            or revision.state != "RELEASED"
            or revision.content_sha256 != generation.execution_preset_sha256
            or revision.retrieval_policy is None
        ):
            _fail(
                "PRODUCTION_EXECUTION_PRESET_POINTER_STALE",
                "the execution's pinned preset revision no longer resolves",
            )
        retrieval = revision.retrieval_policy
        if "integrated-science-textbooks" not in retrieval.allowed_corpus_keys:
            _fail(
                "PRODUCTION_ACCESS_POLICY_SCOPE_INVALID",
                "the pinned access policy does not admit the production corpus",
            )
        return MockExamAccessPolicyPointer(
            access_policy_revision_id=retrieval.access_policy_revision_id,
            access_policy_sha256=retrieval.access_policy_sha256,
        )


def _fail(code: str, message: str) -> Never:
    raise MockExamProductionReleaseError(code, message)
