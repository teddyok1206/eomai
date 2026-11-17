"""Optional Kakao result type: importing ordinary workflow models does not load this wheel."""

from eom_kakao_archive_contracts.concepts import ConceptResult

from .models import KakaoConceptRoleResultHeader


class KakaoConceptRoleResult(KakaoConceptRoleResultHeader):
    output: ConceptResult
