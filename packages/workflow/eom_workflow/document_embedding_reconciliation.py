"""Schema-first separate GPU catch-up intent; no source or physical allocation authority."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_plan import BATCH_PLAN_SCHEMA_REF, embedding_batch_plan_schema
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
)
from eom_workflow.embedding_batch_plan_values import EmbeddingBatchPlanValue
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    SupportedLocalEmbeddingStepOutput,
    parse_supported_local_embedding_step_output,
)
from eom_workflow.models import JobId
from eom_workflow.schemas import local_embedding_receipt_schema_registry

DOCUMENT_RECONCILIATION_PROTOCOL = "document-embedding-reconcile/1.0"
DOCUMENT_RECONCILIATION_SCHEMA_REF = "eom://schemas/workflow/document-embedding-reconcile/1.0"
DOCUMENT_RECONCILIATION_SCHEMA_SHA256 = (
    "sha256:7d146a38129b1eff1b9dff6c6d319947e1a6a8427b8d25b4fe2a57f2022da8ae"
)
MAX_DOCUMENT_RECONCILIATION_BYTES = 16 * 1024


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("DOCUMENT_RECONCILIATION_INVALID")


def document_reconciliation_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/document-embedding-reconciliation-v1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_DOCUMENT_RECONCILIATION_BYTES + 1)
    _require(0 < len(raw) <= MAX_DOCUMENT_RECONCILIATION_BYTES)
    _require(sha256_bytes(raw) == DOCUMENT_RECONCILIATION_SCHEMA_SHA256)
    schema: dict[str, Any] = json.loads(raw)
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = document_reconciliation_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_receipt_schema_registry().with_resource(
        BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class _ReconciliationMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["document-embedding-reconcile/1.0"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            value = raw_similarity_contract_value(value)
            _require(len(canonical_json_bytes(value)) <= MAX_DOCUMENT_RECONCILIATION_BYTES)
            _validator().validate(value)
            return value
        except Exception:
            raise ValueError("DOCUMENT_RECONCILIATION_INVALID") from None


class DocumentEmbeddingReconciliationRequest(_ReconciliationMessage):
    message_type: Literal["REQUEST"]
    source_request_sha256: Sha256
    origin_parent_job_id: JobId
    origin_parent_request_sha256: Sha256
    scope: EmbeddingWorkBatchScope
    cpu_request_sha256: Sha256
    cpu_output: SupportedLocalEmbeddingStepOutput
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        parse_supported_local_embedding_step_output(self.cpu_output)
        _require(
            self.request_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        )
        return self


class DocumentEmbeddingReconciliationAttempt(_ReconciliationMessage):
    message_type: Literal["ATTEMPT"]
    reconciliation_request_sha256: Sha256
    ordinal: int = Field(strict=True, ge=1, le=1_000_000)
    batch_id: str = Field(pattern=r"^embeddingbatch_[0-9a-f]{32}$", strict=True)
    previous_parent_job_id: JobId
    previous_parent_request_sha256: Sha256
    parent_request_sha256: Sha256
    intent_sha256: Sha256

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        identity = content_sha256(
            dict(
                request=self.reconciliation_request_sha256,
                ordinal=self.ordinal,
                previous_job=self.previous_parent_job_id,
                previous_parent=self.previous_parent_request_sha256,
            )
        )
        _require(self.batch_id == "embeddingbatch_" + identity.removeprefix("sha256:")[:32])
        _require(self.parent_request_sha256 != self.previous_parent_request_sha256)
        _require(
            self.intent_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"intent_sha256"}))
        )
        return self


class DocumentEmbeddingReconciliationCompleted(_ReconciliationMessage):
    message_type: Literal["COMPLETED"]
    reconciliation_request_sha256: Sha256
    intent_sha256: Sha256
    output: SupportedLocalEmbeddingStepOutput
    completion_sha256: Sha256

    @model_validator(mode="after")
    def exact_completion(self) -> Self:
        parse_supported_local_embedding_step_output(self.output)
        _require(
            self.completion_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"completion_sha256"}))
        )
        return self


def document_reconciliation_parent(
    base: SupportedEmbeddingBatchRequest,
    intent: DocumentEmbeddingReconciliationAttempt,
) -> SupportedEmbeddingBatchRequest:
    """Pure planned identity, never a Plan Job pointer or a dispatch capability."""
    base = parse_embedding_batch_plan_request(base)
    intent = DocumentEmbeddingReconciliationAttempt.model_validate(intent)
    _require(base.purpose == "INDEX")
    body = base.model_dump(mode="json", exclude={"request_sha256"}) | {"batch_id": intent.batch_id}
    parent = parse_embedding_batch_plan_request(body | {"request_sha256": content_sha256(body)})
    _require(parent.request_sha256 == intent.parent_request_sha256)
    return parent


def prepare_document_reconciliation_intent(
    request: DocumentEmbeddingReconciliationRequest,
    base: SupportedEmbeddingBatchRequest,
    *,
    ordinal: int,
    previous_parent_job_id: str,
    previous_parent_request_sha256: str,
) -> DocumentEmbeddingReconciliationAttempt:
    """The append-only owner separately checks original completion and serializes the head."""
    request = DocumentEmbeddingReconciliationRequest.model_validate(request)
    base = parse_embedding_batch_plan_request(base)
    _require(
        base.purpose == "INDEX"
        and base.parent_request_sha256 == request.source_request_sha256
        and base.request_sha256 == request.origin_parent_request_sha256
        and base.scope == request.scope
    )
    identity = content_sha256(
        dict(
            request=request.request_sha256,
            ordinal=ordinal,
            previous_job=previous_parent_job_id,
            previous_parent=previous_parent_request_sha256,
        )
    )
    batch_id = "embeddingbatch_" + identity.removeprefix("sha256:")[:32]
    parent = base.model_dump(mode="json", exclude={"request_sha256"}) | {"batch_id": batch_id}
    body = dict(
        schema_version=DOCUMENT_RECONCILIATION_PROTOCOL,
        message_type="ATTEMPT",
        reconciliation_request_sha256=request.request_sha256,
        ordinal=ordinal,
        batch_id=batch_id,
        previous_parent_job_id=previous_parent_job_id,
        previous_parent_request_sha256=previous_parent_request_sha256,
        parent_request_sha256=content_sha256(parent),
    )
    return DocumentEmbeddingReconciliationAttempt.model_validate(
        body | {"intent_sha256": content_sha256(body)}
    )
