"""Compose accepted-content reads; actual collection admission remains disabled here."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import Engine

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_knowledge import KakaoConceptKnowledgeReader
from .kakao_concept_task_service import KakaoConceptTaskService
from .kakao_question_compose_service import KakaoQuestionComposeService
from .kakao_question_reads import KakaoQuestionReads
from .kakao_question_service import KakaoQuestionService
from .kakao_source_service import KakaoSourceService

if TYPE_CHECKING:
    from .kakao_concept_continuation import KakaoConceptCoordinator


@dataclass(frozen=True, slots=True)
class KakaoQuestionApplication:
    questions: KakaoQuestionService
    reads: KakaoQuestionReads
    composer: KakaoQuestionComposeService | None = None
    concepts: KakaoConceptTaskService | None = None
    concept_coordinator: "KakaoConceptCoordinator | None" = None


def build_kakao_question_application(
    engine: Engine, *, concept_mode: str = "DISABLED"
) -> KakaoQuestionApplication:
    if concept_mode not in {"DISABLED", "SHARED"}:
        raise ValueError("KAKAO_CONCEPT_MODE_INVALID")
    artifacts = CatalogArtifactService(engine)

    def capture_not_configured(*_args: object) -> None:
        # This composition exposes no source-admission method. A future actual
        # collection owner must inject its accepted capture authority, not a bool.
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")

    sources = KakaoSourceService(
        engine, artifacts=artifacts, authorize_capture=capture_not_configured
    )
    questions = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    knowledge = KakaoConceptKnowledgeReader(engine, artifacts.settings)
    concepts = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=questions,
        sources=sources,
        scope_provider=knowledge.capture_authoring_scope,
        knowledge_reader=knowledge,
    )
    coordinator = None
    if concept_mode == "SHARED":
        from .kakao_concept_continuation import KakaoConceptCoordinator

        coordinator = KakaoConceptCoordinator(concepts)
    return KakaoQuestionApplication(
        questions,
        KakaoQuestionReads(engine, questions=questions, sources=sources, artifacts=artifacts),
        KakaoQuestionComposeService(
            engine, questions=questions, sources=sources, artifacts=artifacts
        ),
        concepts,
        coordinator,
    )
