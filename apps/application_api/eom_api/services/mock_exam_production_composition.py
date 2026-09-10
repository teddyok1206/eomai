"""Production composition root for the resumable 25-by-one-Item pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from eom_api_contracts.mock_exam_execution import MockExamWorkflowKnowledgeProvenancePointerV3
from eom_catalog_contracts.item_review import MockExamTrustedEvidenceUsageReceiptPairV1
from eom_catalog_service.evidence_usage_receipts import (
    EvidenceUsageProvenanceExpectation,
    OrchestratorEvidenceUsageReceiptResolver,
)
from eom_orchestrator.capacity_controller import CodexCapacityController
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.mock_exam_production_retirement import (
    MockExamProductionRetirementService,
)
from eom_workflow_runner.systemd_retirement_quiescence import (
    SystemdWorkflowRunnerQuiescenceAdapter,
)

from eom_api.services.mock_exam_generation_block_resolver import (
    DatabaseGenerationBlockResolver,
)
from eom_api.services.mock_exam_production_application import (
    MockExamOperatorAuthenticator,
    MockExamProductionApplicationService,
    MockExamProductionDeliverableService,
)
from eom_api.services.mock_exam_production_checkpoint_store import (
    AtomicJsonMockExamProductionCheckpointStore,
)
from eom_api.services.mock_exam_production_coordinator import (
    CatalogApprovedItemAnalysisOperations,
    CatalogApprovedItemGraphOperations,
    CatalogMockExamRatingOperations,
    CatalogReviewEligibilityReader,
    ExistingAssessmentHwpxOperations,
    ExistingMockExamAssemblyOperations,
    ExistingOneItemWorkflowOperations,
    MockExamProductionCoordinator,
)
from eom_api.services.mock_exam_production_release_resolver import (
    DatabaseAnalysisPolicyPointerReader,
    ReleasedMockExamProductionResolver,
)
from eom_api.services.mock_exam_production_runner import MockExamProductionRunner

if TYPE_CHECKING:
    from eom_api.lifespan import AppServices


@dataclass(frozen=True)
class MockExamProductionRuntime:
    """Explicitly composed application and authentication boundaries."""

    application: MockExamProductionApplicationService
    authenticator: MockExamOperatorAuthenticator


class _DatabaseTrustedEvidenceUsageReceiptVerifier:
    """Composition adapter keeping orchestrator persistence outside coordinator rules."""

    def __init__(self, services: AppServices) -> None:
        self._resolver = OrchestratorEvidenceUsageReceiptResolver(
            build_session_factory(services.engine)
        )

    def verify(
        self,
        *,
        receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
        knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV3,
    ) -> None:
        self._resolver.verify_mock_exam_pair(
            receipts=receipts,
            expected_provenance=EvidenceUsageProvenanceExpectation(
                plan_id=knowledge_provenance.plan_id,
                plan_sha256=knowledge_provenance.plan_sha256,
                evidence_bundle_revision_id=(knowledge_provenance.evidence_bundle_revision_id),
                retrieval_request_id=knowledge_provenance.retrieval_request_id,
                retrieval_request_sha256=knowledge_provenance.retrieval_request_sha256,
                graph_snapshot_revision_id=(knowledge_provenance.graph_snapshot_revision_id),
                evidence_manifest_sha256=knowledge_provenance.evidence_manifest_sha256,
            ),
        )


def build_mock_exam_production_runtime(
    services: AppServices,
    *,
    checkpoint_root: Path,
) -> MockExamProductionRuntime:
    """Compose existing application adapters without giving the CLI DB/NAS/worker access."""

    generation_blocks = DatabaseGenerationBlockResolver(
        services.engine,
        environment="development",
    )
    releases = ReleasedMockExamProductionResolver(
        analysis_policies=DatabaseAnalysisPolicyPointerReader(services.engine),
        presets=services.control_plane,
    )
    workflows = ExistingOneItemWorkflowOperations(
        services.commands,
        services.queries,
        generation_blocks,
        CatalogReviewEligibilityReader(
            services.catalog_application,
            _DatabaseTrustedEvidenceUsageReceiptVerifier(services),
        ),
    )
    coordinator = MockExamProductionCoordinator(
        workflows=workflows,
        analyses=CatalogApprovedItemAnalysisOperations(
            services.catalog_application,
            services.queries,
        ),
        graph=CatalogApprovedItemGraphOperations(services.catalog_application),
        ratings=CatalogMockExamRatingOperations(services.catalog_application),
        assemblies=ExistingMockExamAssemblyOperations(
            services.commands,
            services.queries,
        ),
        hwpx=ExistingAssessmentHwpxOperations(services.exam_hwpx),
    )
    runner = MockExamProductionRunner(
        coordinator=coordinator,
        checkpoints=AtomicJsonMockExamProductionCheckpointStore(checkpoint_root),
        retirements=MockExamProductionRetirementService(
            services.engine,
            quiescence=SystemdWorkflowRunnerQuiescenceAdapter(),
            lease_reconciler=CodexCapacityController(
                build_session_factory(services.engine),
            ),
        ),
    )
    return MockExamProductionRuntime(
        application=MockExamProductionApplicationService(
            runner=runner,
            releases=releases,
            deliverables=MockExamProductionDeliverableService(
                services.commands,
                services.queries,
            ),
            fresh_auth_seconds=services.settings.auth.fresh_auth_seconds,
        ),
        authenticator=MockExamOperatorAuthenticator(services.auth),
    )
