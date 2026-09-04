"""Long-running orchestrator-owned Catalog application boundary."""

from __future__ import annotations

import argparse
import os
import signal
import threading

from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_engine

from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_content_import import StructuredItemContentImportService
from eom_catalog_service.knowledge_analysis_batch_models import (
    KnowledgeAnalysisBatchRangeRecord,
    KnowledgeAnalysisBatchRecord,
)
from eom_catalog_service.knowledge_analysis_batch_service import KnowledgeAnalysisBatchService
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.legacy_assessment_rights import (
    RegisteredAssessmentRightsPolicyResolver,
)
from eom_catalog_service.legacy_item_acceptance_service import (
    AutomaticLegacyItemAcceptanceService,
    LegacyItemAcceptanceService,
)
from eom_catalog_service.legacy_item_automation_service import (
    LegacyItemAutomaticLearningService,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_service import (
    LegacyItemExtractionBatchService,
)
from eom_catalog_service.legacy_item_learning_service import LegacyItemLearningCoordinator
from eom_catalog_service.legacy_item_promotion_service import LegacyItemPromotionService
from eom_catalog_service.legacy_usage_models import LegacyUsageImportRecord
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.runtime_privileges import catalog_runtime_privileges_ready

_RUNTIME_MODEL_TABLES = (
    OperatorRecord.__table__,
    LegacyUsageImportRecord.__table__,
    KnowledgeAnalysisBatchRecord.__table__,
    KnowledgeAnalysisBatchRangeRecord.__table__,
    LegacyItemExtractionBatchRecord.__table__,
    LegacyItemExtractionBatchWorkUnitRecord.__table__,
)


def serve() -> int:
    engine = build_engine()
    server: CatalogApplicationServer | None = None
    thread: threading.Thread | None = None
    stopping = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with engine.connect() as connection:
            if not catalog_runtime_privileges_ready(connection):
                print("CATALOG_RUNTIME_DATABASE_PRIVILEGES_UNAVAILABLE", flush=True)
                return 1
        automation_mode = os.environ.get("EOM_LEGACY_ITEM_AUTOMATION_MODE", "DISABLED")
        if automation_mode not in {"DISABLED", "AUTO_ACCEPT_AND_LEARN"}:
            print("LEGACY_ITEM_AUTOMATION_MODE_INVALID", flush=True)
            return 1
        knowledge_analysis = KnowledgeAnalysisApplicationService(engine)
        knowledge_analysis_batches = KnowledgeAnalysisBatchService(
            engine,
            analysis=knowledge_analysis,
        )
        automatic_acceptance = None
        automatic_learning = None
        if automation_mode == "AUTO_ACCEPT_AND_LEARN":
            extraction_batch_id = os.environ.get("EOM_LEGACY_ITEM_AUTOMATION_BATCH_ID")
            content_pack_release_id = os.environ.get("EOM_LEGACY_ITEM_AUTOMATION_PACK_RELEASE_ID")
            risk_policy_revision_id = os.environ.get(
                "EOM_LEGACY_ITEM_AUTOMATION_RISK_POLICY_REVISION_ID"
            )
            if (
                not extraction_batch_id
                or not content_pack_release_id
                or not risk_policy_revision_id
            ):
                print("LEGACY_ITEM_AUTOMATION_CONFIGURATION_INCOMPLETE", flush=True)
                return 1
            artifacts = CatalogArtifactService(engine)
            rights = RegisteredAssessmentRightsPolicyResolver(engine)
            acceptance = LegacyItemAcceptanceService(
                engine,
                rights=rights,
                artifacts=artifacts,
            )
            automatic_acceptance = AutomaticLegacyItemAcceptanceService(
                engine,
                acceptance=acceptance,
                artifacts=artifacts,
            )
            promotion = LegacyItemPromotionService(
                engine,
                rights=rights,
                artifacts=artifacts,
            )
            learning = LegacyItemLearningCoordinator(
                engine,
                promotion=promotion,
                analyses=knowledge_analysis,
            )
            automatic_learning = LegacyItemAutomaticLearningService(
                engine,
                extraction_batch_id=extraction_batch_id,
                content_pack_release_id=content_pack_release_id,
                risk_policy_revision_id=risk_policy_revision_id,
                learning=learning,
                analyses=knowledge_analysis,
            )
        legacy_extraction_batches = LegacyItemExtractionBatchService(
            engine,
            automatic_acceptance=automatic_acceptance,
        )
        server = CatalogApplicationServer(
            StructuredItemContentImportService(engine),
            RegistryService(engine),
            knowledge_analysis,
            knowledge_analysis_batches,
            KnowledgeRetrievalApplicationService(engine),
        )
        thread = threading.Thread(
            target=server.serve_forever,
            name="eom-catalog-application",
            daemon=True,
        )
        thread.start()
        runner_id = f"catalog-batch-runner:{os.getpid()}"
        while not stopping.wait(timeout=1):
            if not thread.is_alive():
                return 1
            try:
                knowledge_analysis_batches.advance_once(runner_id=runner_id)
            except Exception:
                # The durable claim/idempotency contract owns recovery. Do not expose source data.
                print("KNOWLEDGE_ANALYSIS_BATCH_RUNNER_ERROR", flush=True)
            if automatic_learning is not None:
                try:
                    automatic_learning.advance_once()
                except Exception:
                    # Exact Artifact and request identities make this application step replayable.
                    print("LEGACY_ITEM_AUTOMATION_RUNNER_ERROR", flush=True)
            try:
                legacy_extraction_batches.advance_once(runner_id=runner_id)
            except Exception:
                # The manifest, claim, and workflow receipts own recovery; keep logs content-free.
                print("LEGACY_ITEM_EXTRACTION_BATCH_RUNNER_ERROR", flush=True)
        return 0
    except Exception:
        return 1
    finally:
        if server is not None and thread is not None and thread.is_alive():
            server.shutdown()
        if server is not None:
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="eom-catalog-application-runner")
    parser.add_argument("command", choices=("serve",))
    arguments = parser.parse_args()
    if arguments.command != "serve":  # pragma: no cover - argparse owns the invariant
        parser.error("unsupported command")
    raise SystemExit(serve())


if __name__ == "__main__":
    main()
