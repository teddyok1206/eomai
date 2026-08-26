"""Long-running orchestrator-owned Catalog application boundary."""

from __future__ import annotations

import argparse
import os
import signal
import threading

from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_engine

from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.item_content_import import StructuredItemContentImportService
from eom_catalog_service.knowledge_analysis_batch_models import (
    KnowledgeAnalysisBatchRangeRecord,
    KnowledgeAnalysisBatchRecord,
)
from eom_catalog_service.knowledge_analysis_batch_service import KnowledgeAnalysisBatchService
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.legacy_usage_models import LegacyUsageImportRecord
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.runtime_privileges import catalog_runtime_privileges_ready

_RUNTIME_MODEL_TABLES = (
    OperatorRecord.__table__,
    LegacyUsageImportRecord.__table__,
    KnowledgeAnalysisBatchRecord.__table__,
    KnowledgeAnalysisBatchRangeRecord.__table__,
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
        knowledge_analysis = KnowledgeAnalysisApplicationService(engine)
        knowledge_analysis_batches = KnowledgeAnalysisBatchService(
            engine,
            analysis=knowledge_analysis,
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
