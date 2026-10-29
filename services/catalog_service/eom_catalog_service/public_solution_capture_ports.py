"""Small Catalog capture result, without loading Workflow execution adapters."""

from dataclasses import dataclass

from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry

from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferCorpus
from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent


@dataclass(frozen=True, slots=True)
class CapturedPublicSolutionSources:
    entries: tuple[PublicSolutionEmbeddingEntry, ...]
    missing_report_revision_ids: tuple[str, ...]
    source_revision_ids: tuple[str, ...]
    scope: ReadOnlyCandidatePoolScope | LocalIndexingSourceReadIntent
    corpus: AdmittedInferenceTransferCorpus | None
