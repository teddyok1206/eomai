"""Compose accepted-content reads; actual collection admission remains disabled here."""

from dataclasses import dataclass

from sqlalchemy import Engine

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import KakaoArchiveError
from .kakao_question_reads import KakaoQuestionReads
from .kakao_question_service import KakaoQuestionService
from .kakao_source_service import KakaoSourceService


@dataclass(frozen=True, slots=True)
class KakaoQuestionApplication:
    questions: KakaoQuestionService
    reads: KakaoQuestionReads


def build_kakao_question_application(engine: Engine) -> KakaoQuestionApplication:
    artifacts = CatalogArtifactService(engine)

    def capture_not_configured(*_args: object) -> None:
        # This composition exposes no source-admission method. A future actual
        # collection owner must inject its accepted capture authority, not a bool.
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")

    sources = KakaoSourceService(
        engine, artifacts=artifacts, authorize_capture=capture_not_configured
    )
    questions = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    return KakaoQuestionApplication(
        questions,
        KakaoQuestionReads(engine, questions=questions, sources=sources, artifacts=artifacts),
    )
