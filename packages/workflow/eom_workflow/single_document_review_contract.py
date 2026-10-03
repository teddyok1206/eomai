"""Exact single-document result policy identities, independent of runtime activation."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True)
class SingleDocumentReviewContract:
    definition_version: str
    protocol_version: Literal["workflow-role/1.25.0", "workflow-role/1.28.0"]
    result_schema: Literal["pdf-document-review-result@1.0", "pdf-document-review-result@4.0"]
    schema_ref: Literal[
        "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json",
        "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v4.schema.json",
    ]


LEGACY_SINGLE_DOCUMENT_REVIEW = SingleDocumentReviewContract(
    "1.0.0",
    "workflow-role/1.25.0",
    "pdf-document-review-result@1.0",
    "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json",
)
CURRENT_SINGLE_DOCUMENT_REVIEW = SingleDocumentReviewContract(
    "1.3.0",
    "workflow-role/1.28.0",
    "pdf-document-review-result@4.0",
    "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v4.schema.json",
)
_CONTRACTS = (LEGACY_SINGLE_DOCUMENT_REVIEW, CURRENT_SINGLE_DOCUMENT_REVIEW)
_BY_DEFINITION = MappingProxyType({value.definition_version: value for value in _CONTRACTS})
_BY_SCHEMA: MappingProxyType[str, SingleDocumentReviewContract] = MappingProxyType(
    {value.result_schema: value for value in _CONTRACTS}
)
_BY_SCHEMA_REF: MappingProxyType[str, SingleDocumentReviewContract] = MappingProxyType(
    {value.schema_ref: value for value in _CONTRACTS}
)


def single_document_review_contract_for_definition(version: str) -> SingleDocumentReviewContract:
    try:
        return _BY_DEFINITION[version]
    except KeyError:
        raise ValueError("unsupported single-document review definition") from None


def single_document_review_contract_for_schema(schema: str) -> SingleDocumentReviewContract:
    try:
        return _BY_SCHEMA[schema]
    except KeyError:
        raise ValueError("unsupported single-document review result schema") from None


def single_document_review_contract_for_schema_ref(schema_ref: str) -> SingleDocumentReviewContract:
    try:
        return _BY_SCHEMA_REF[schema_ref]
    except KeyError:
        raise ValueError("unsupported single-document review result pointer schema") from None
