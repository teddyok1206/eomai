"""Production composition root for the resumable 25-by-one-Item pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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
        CatalogReviewEligibilityReader(services.catalog_application),
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
