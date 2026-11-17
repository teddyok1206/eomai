"""Public question reads/reviews reuse the Catalog-owned revision and projection contracts."""

from typing import Annotated

from eom_catalog_contracts.kakao_question import KakaoQuestionConfirm, KakaoQuestionExclude
from eom_catalog_contracts.kakao_question_candidates import KakaoQuestionCandidatePage
from eom_catalog_contracts.kakao_question_composition import KakaoQuestionComposition
from eom_catalog_contracts.kakao_question_composition_result import KakaoQuestionCompositionResult
from eom_catalog_contracts.kakao_question_edit_context import KakaoQuestionEditContext
from eom_catalog_contracts.kakao_question_refresh import KakaoQuestionSourceRefresh
from eom_catalog_contracts.kakao_question_rpc import KakaoQuestionView
from eom_catalog_contracts.kakao_question_store import (
    KakaoQuestionCreate,
    KakaoQuestionMutation,
    KakaoQuestionPage,
)
from pydantic import Field

KakaoQuestionReview = Annotated[
    KakaoQuestionConfirm | KakaoQuestionExclude, Field(discriminator="action")
]

__all__ = [
    "KakaoQuestionCandidatePage",
    "KakaoQuestionComposition",
    "KakaoQuestionCompositionResult",
    "KakaoQuestionCreate",
    "KakaoQuestionEditContext",
    "KakaoQuestionMutation",
    "KakaoQuestionPage",
    "KakaoQuestionReview",
    "KakaoQuestionSourceRefresh",
    "KakaoQuestionView",
]
