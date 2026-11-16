"""Public question reads/reviews reuse the Catalog-owned revision and projection contracts."""

from typing import Annotated

from eom_catalog_contracts.kakao_question import KakaoQuestionConfirm, KakaoQuestionExclude
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
    "KakaoQuestionCreate",
    "KakaoQuestionMutation",
    "KakaoQuestionPage",
    "KakaoQuestionReview",
    "KakaoQuestionView",
]
