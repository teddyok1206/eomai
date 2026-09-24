"""Deterministic document-to-Graph scope planning for paired review."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Literal

from eom_catalog_contracts import (
    CreateDocumentReviewEvidenceCommand,
    CreateItemProductionEvidenceCommand,
    DocumentReviewEvidenceExtractor,
    DocumentReviewEvidencePlan,
    DocumentReviewEvidenceSourceIdentity,
    EducationalRetrievalRequirement,
    EvidenceBundlePublicationResultV5,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, func, select

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeTermRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
)

_PDFTOTEXT = Path("/usr/bin/pdftotext")
_MAX_TEXT_BYTES = 8 * 1024 * 1024
_MAX_TERMS = 512
_MAX_TERM_ROWS = 131_072
_MAX_TOPIC_KEYS = 20
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,64}", re.ASCII)
_TOPIC_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$", re.ASCII)
_REQUIRED_ELEMENTS: tuple[
    Literal["choice", "equation", "image", "paragraph", "statement_set", "table"], ...
] = ("choice", "equation", "image", "paragraph", "statement_set", "table")


class DocumentReviewEvidenceServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _rank_topic_key_rows(
    rows: tuple[tuple[str, str, int], ...],
    *,
    limit: int = _MAX_TOPIC_KEYS,
) -> tuple[str, ...]:
    """Rank indexed term matches and return a canonical bounded topic-key set."""

    scores: dict[str, int] = {}
    for _term, stable_key, term_frequency in rows:
        if _TOPIC_KEY.fullmatch(stable_key) is None:
            continue
        scores[stable_key] = scores.get(stable_key, 0) + max(
            1,
            1_000_000 // term_frequency,
        )
    ranked = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
    return tuple(sorted(ranked))


class DocumentReviewEvidenceService:
    """Resolve exact PDF bytes to bounded indexed topics and an immutable Evidence Bundle."""

    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService | None = None,
        retrieval: KnowledgeRetrievalApplicationService | None = None,
        pdftotext_path: Path = _PDFTOTEXT,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine)
        self.retrieval = retrieval or KnowledgeRetrievalApplicationService(engine)
        self.pdftotext_path = pdftotext_path

    def create(self, command: CreateDocumentReviewEvidenceCommand) -> DocumentReviewEvidencePlan:
        extractor_sha256, descriptor = self._open_extractor()
        try:
            terms: set[str] = set()
            for source in command.documents:
                pointer = source.document.source_pdf
                payload = self.artifacts.read_member(
                    artifact_id=pointer.artifact_id,
                    revision_id=pointer.artifact_revision_id,
                    member_path=pointer.member_path,
                    sha256=pointer.sha256,
                    media_type=pointer.media_type,
                    schema_ref=pointer.schema_ref,
                    max_bytes=256 * 1024 * 1024,
                )
                terms.update(self._extract_terms(descriptor, payload))
        finally:
            os.close(descriptor)
        bounded_terms = tuple(sorted(terms)[:_MAX_TERMS])
        if not bounded_terms:
            raise DocumentReviewEvidenceServiceError(
                "DOCUMENT_REVIEW_EVIDENCE_TEXT_MISSING",
                "document review sources contain no bounded extractable text",
            )
        topic_keys = self._resolve_topic_keys(command.corpus_key, bounded_terms)
        if not topic_keys:
            raise DocumentReviewEvidenceServiceError(
                "DOCUMENT_REVIEW_EVIDENCE_SCOPE_MISSING",
                "document review text does not resolve to controlled Graph topics",
            )
        requirement = EducationalRetrievalRequirement(
            corpus_key=command.corpus_key,
            query_kind="ITEM_PREPARATION",
            curriculum_root_key=None,
            topic_keys=topic_keys,
            required_item_elements=_REQUIRED_ELEMENTS,
            source_classes=command.source_classes,
        )
        command_value = {
            "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
            "requirement": requirement.model_dump(mode="json"),
            "evidence_budget": command.evidence_budget.model_dump(mode="json"),
            "access_policy_revision_id": command.access_policy_revision_id,
            "access_policy_sha256": command.access_policy_sha256,
            "requester_role": command.requester_role,
            "requester_permission_keys": list(command.requester_permission_keys),
            "requested_by": command.requested_by,
            "solution_evidence_requirement": "REQUIRE_ACCEPTED_SOLUTION_REPORT",
        }
        command_value["submission_sha256"] = content_sha256(command_value)
        command_value["idempotency_key"] = "document-review-evidence:" + content_sha256(
            {
                "idempotency_key": command.idempotency_key,
                "submission_sha256": command.submission_sha256,
            }
        ).removeprefix("sha256:")
        publication = self.retrieval.create_item_production(
            CreateItemProductionEvidenceCommand.model_validate(command_value)
        )
        if not isinstance(publication, EvidenceBundlePublicationResultV5):
            raise DocumentReviewEvidenceServiceError(
                "DOCUMENT_REVIEW_EVIDENCE_SOLUTION_MISSING",
                "document review requires solution-enriched Graph evidence",
            )
        document: dict[str, object] = {
            "schema_version": "document-review-evidence-plan/1.0",
            "documents": [
                DocumentReviewEvidenceSourceIdentity(
                    role=value.role,
                    document_id=value.document.document_id,
                    document_revision_id=value.document.document_revision_id,
                    source_pdf_sha256=value.document.source_pdf.sha256,
                ).model_dump(mode="json")
                for value in command.documents
            ],
            "term_set_sha256": content_sha256(list(bounded_terms)),
            "topic_keys": list(topic_keys),
            "extractor": DocumentReviewEvidenceExtractor(
                executable_sha256=extractor_sha256
            ).model_dump(mode="json"),
            "requirement": requirement.model_dump(mode="json"),
            "publication": publication.model_dump(mode="json"),
        }
        document["plan_sha256"] = content_sha256(document)
        return DocumentReviewEvidencePlan.model_validate(document)

    def _open_extractor(self) -> tuple[str, int]:
        descriptor = -1
        try:
            descriptor = os.open(
                self.pdftotext_path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or metadata.st_gid != 0
                or stat.S_IMODE(metadata.st_mode) != 0o755
                or metadata.st_nlink != 1
                or metadata.st_size < 1
                or metadata.st_size > 64 * 1024 * 1024
            ):
                raise OSError("pdftotext identity differs")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            os.lseek(descriptor, 0, os.SEEK_SET)
            return "sha256:" + digest.hexdigest(), descriptor
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise DocumentReviewEvidenceServiceError(
                "DOCUMENT_REVIEW_EVIDENCE_EXTRACTOR_INVALID",
                "root-owned PDF text extractor is unavailable",
            ) from exc

    def _extract_terms(self, extractor_descriptor: int, payload: bytes) -> set[str]:
        staging_root = self.artifacts.settings.staging_root
        with tempfile.TemporaryDirectory(
            prefix="document-review-evidence.", dir=staging_root
        ) as raw_directory:
            directory = Path(raw_directory)
            source = directory / "source.pdf"
            output = directory / "source.txt"
            source.write_bytes(payload)
            source.chmod(0o600)
            try:
                completed = subprocess.run(
                    [f"/proc/self/fd/{extractor_descriptor}", "-layout", str(source), str(output)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    check=False,
                    env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"},
                    pass_fds=(extractor_descriptor,),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DocumentReviewEvidenceServiceError(
                    "DOCUMENT_REVIEW_EVIDENCE_EXTRACTION_FAILED",
                    "bounded PDF text extraction failed",
                ) from exc
            if completed.returncode != 0:
                raise DocumentReviewEvidenceServiceError(
                    "DOCUMENT_REVIEW_EVIDENCE_EXTRACTION_FAILED",
                    "bounded PDF text extraction failed",
                )
            try:
                metadata = output.lstat()
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or metadata.st_size > _MAX_TEXT_BYTES
                ):
                    raise OSError("extracted text identity differs")
                raw = output.read_bytes()
                text = raw.decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise DocumentReviewEvidenceServiceError(
                    "DOCUMENT_REVIEW_EVIDENCE_TEXT_INVALID",
                    "extracted document text is invalid",
                ) from exc
        normalized = unicodedata.normalize("NFKC", text).lower()
        return set(_TOKEN.findall(normalized))

    def _resolve_topic_keys(self, corpus_key: str, terms: tuple[str, ...]) -> tuple[str, ...]:
        with self.sessions() as session:
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(KnowledgeCorpusRecord.corpus_key == corpus_key)
            )
            snapshot = (
                session.get(
                    KnowledgeGraphSnapshotRecord,
                    corpus.current_graph_snapshot_revision_id,
                )
                if corpus is not None and corpus.current_graph_snapshot_revision_id is not None
                else None
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or snapshot is None
                or snapshot.state != "PUBLISHED"
            ):
                raise DocumentReviewEvidenceServiceError(
                    "DOCUMENT_REVIEW_EVIDENCE_CORPUS_UNAVAILABLE",
                    "document review corpus has no published current Graph snapshot",
                )
            frequency = func.count().over(partition_by=KnowledgeNodeTermRecord.term)
            rows = tuple(
                session.execute(
                    select(
                        KnowledgeNodeTermRecord.term,
                        KnowledgeNodeRecord.stable_key,
                        frequency.label("term_frequency"),
                    )
                    .join(
                        KnowledgeNodeRecord,
                        (
                            KnowledgeNodeRecord.graph_snapshot_revision_id
                            == KnowledgeNodeTermRecord.graph_snapshot_revision_id
                        )
                        & (KnowledgeNodeRecord.node_id == KnowledgeNodeTermRecord.node_id),
                    )
                    .where(
                        KnowledgeNodeTermRecord.graph_snapshot_revision_id
                        == snapshot.graph_snapshot_revision_id,
                        KnowledgeNodeTermRecord.term.in_(terms),
                    )
                    .order_by(
                        frequency,
                        KnowledgeNodeTermRecord.term,
                        KnowledgeNodeRecord.stable_key,
                    )
                    .limit(_MAX_TERM_ROWS)
                )
            )
        return _rank_topic_key_rows(
            tuple(
                (str(term), str(stable_key), int(frequency)) for term, stable_key, frequency in rows
            )
        )
