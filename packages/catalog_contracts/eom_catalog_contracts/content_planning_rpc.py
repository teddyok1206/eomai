"""Closed Catalog peer messages: no caller-supplied roles, SQL, paths or latest pins."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, TypeAdapter, model_validator

from eom_catalog_contracts.content_delivery import (
    ContentDeliveryList,
    ContentDeliveryPrepared,
    PrepareContentDelivery,
    ReadContentDeliveries,
)
from eom_catalog_contracts.content_planning_commands import (
    ContentPlanningCommand,
    ContentPlanningWriteResult,
    CopyContentEdition,
    CreateContentEdition,
    CreatePlannedContent,
    EditContentEdition,
)
from eom_catalog_contracts.content_planning_queries import (
    ContentPlanningQuery,
    ContentPlanningQueryResult,
)
from eom_catalog_contracts.content_print_commands import (
    ContentPrintCommand,
    ContentPrintMutationResult,
    VoidContentPrint,
)
from eom_catalog_contracts.content_print_views import ContentPrintList, ReadContentPrints
from eom_catalog_contracts.content_usage import (
    ContentUsagePage,
    ContentUsageSummary,
    PriorUsagePage,
    ReadContentUsage,
    ReadContentUsageSummary,
    ReadPriorContentUsage,
)
from eom_catalog_contracts.models import FrozenModel, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

CONTENT_PLANNING_OPERATIONS = frozenset(
    {
        "CONTENT_PLANNING_WRITE",
        "CONTENT_PLANNING_QUERY",
        "CONTENT_PLANNING_PRINT",
        "CONTENT_PLANNING_DELIVERY",
    }
)


class _ApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    authentication_time: UtcDatetime


class ContentPlanningWriteRequest(_ApiIdentity):
    operation: Literal["CONTENT_PLANNING_WRITE"] = "CONTENT_PLANNING_WRITE"
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")
    command: ContentPlanningCommand


class ContentPlanningQueryRequest(_ApiIdentity):
    operation: Literal["CONTENT_PLANNING_QUERY"] = "CONTENT_PLANNING_QUERY"
    query: ContentPlanningQuery


class ContentPlanningPrintRequest(_ApiIdentity):
    operation: Literal["CONTENT_PLANNING_PRINT"] = "CONTENT_PLANNING_PRINT"
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")
    command: ContentPrintCommand


class ContentPlanningDeliveryRequest(_ApiIdentity):
    operation: Literal["CONTENT_PLANNING_DELIVERY"] = "CONTENT_PLANNING_DELIVERY"
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[!-~]{16,128}$")
    command: PrepareContentDelivery


class ContentPlanningReply(FrozenModel):
    operation: Literal[
        "CONTENT_PLANNING_WRITE",
        "CONTENT_PLANNING_QUERY",
        "CONTENT_PLANNING_PRINT",
        "CONTENT_PLANNING_DELIVERY",
    ]
    status: Literal["OK", "ERROR"]
    result: (
        ContentPlanningWriteResult
        | ContentPlanningQueryResult
        | ContentPrintMutationResult
        | ContentDeliveryPrepared
        | None
    ) = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_branch(self) -> Self:
        if self.status == "ERROR":
            if self.result is not None or self.error_code is None:
                raise ValueError("failed planning reply must have only an error code")
        elif (
            self.result is None
            or self.error_code is not None
            or (
                (self.operation == "CONTENT_PLANNING_WRITE")
                != isinstance(self.result, ContentPlanningWriteResult)
            )
            or (
                (self.operation == "CONTENT_PLANNING_PRINT")
                != isinstance(self.result, ContentPrintMutationResult)
            )
            or (
                (self.operation == "CONTENT_PLANNING_DELIVERY")
                != isinstance(self.result, ContentDeliveryPrepared)
            )
        ):
            raise ValueError("planning reply result does not match the operation")
        return self


type ContentPlanningRequest = Annotated[
    ContentPlanningWriteRequest
    | ContentPlanningQueryRequest
    | ContentPlanningPrintRequest
    | ContentPlanningDeliveryRequest,
    Field(discriminator="operation"),
]
_REQUEST: TypeAdapter[ContentPlanningRequest] = TypeAdapter(ContentPlanningRequest)


def parse_content_planning_request(value: dict[str, object]) -> ContentPlanningRequest:
    validate_contract("catalog-content-planning-request-v1", value)
    return _REQUEST.validate_python(value)


def parse_content_planning_reply(value: dict[str, object]) -> ContentPlanningReply:
    validate_contract("catalog-content-planning-response-v1", value)
    return ContentPlanningReply.model_validate(value)


def check_content_planning_reply(
    request: ContentPlanningRequest, reply: ContentPlanningReply
) -> None:
    """Correlate exact read pins before a client renders a valid but unrelated reply."""
    from eom_catalog_contracts.content_planning_queries import (
        ContentEditionList,
        ContentEditionView,
        ContentHistoryPage,
        ContentSectionPage,
        ListContentEditions,
        ReadContentEdition,
        ReadContentHistory,
        ReadContentSection,
    )

    if reply.operation != request.operation:
        raise ValueError("content response operation differs")
    if reply.status == "ERROR":
        return
    if isinstance(request, ContentPlanningDeliveryRequest):
        if not isinstance(reply.result, ContentDeliveryPrepared) or (
            reply.result.edition_id,
            reply.result.revision_id,
            reply.result.composition_sha256,
        ) != (
            request.command.edition_id,
            request.command.revision_id,
            request.command.composition_sha256,
        ):
            raise ValueError("delivery response edition pointer differs")
        return
    if isinstance(request, ContentPlanningPrintRequest):
        if (
            not isinstance(reply.result, ContentPrintMutationResult)
            or reply.result.record.scope.edition_id != request.command.edition_id
        ):
            raise ValueError("print response edition differs")
        if isinstance(request.command, VoidContentPrint) and (
            reply.result.record.print_record_id != request.command.print_record_id
            or reply.result.record.record_sha256 != request.command.record_sha256
        ):
            raise ValueError("print response record differs")
        return
    if isinstance(request, ContentPlanningWriteRequest):
        if not isinstance(reply.result, ContentPlanningWriteResult):
            raise ValueError("content write response kind differs")
        command, composition = request.command, reply.result.composition
        if isinstance(command, EditContentEdition) and composition.edition_id != command.edition_id:
            raise ValueError("content write edition differs")
        if (
            isinstance(command, CreateContentEdition)
            and composition.deliverable_id != command.deliverable_id
        ):
            raise ValueError("content write product differs")
        if (
            isinstance(command, CopyContentEdition)
            and composition.edition_id == command.source_edition_id
        ):
            raise ValueError("content copy reused source edition")
        if isinstance(
            command, (CreatePlannedContent, CreateContentEdition, CopyContentEdition)
        ) and (
            composition.edition_label != command.edition_label
            or composition.academic_year != command.academic_year
        ):
            raise ValueError("content write edition metadata differs")
        if isinstance(command, CreatePlannedContent) and (
            composition.content_title != command.content_title
            or composition.content_type != command.content_type
        ):
            raise ValueError("content write product metadata differs")
        return
    query, result = request.query, reply.result
    kinds = {
        "LIST_CONTENTS": "CONTENTS",
        "LIST_EDITIONS": "EDITIONS",
        "READ_EDITION": "COMPOSITION",
        "READ_SECTION": "SECTION",
        "HISTORY": "HISTORY",
        "PRINTS": "PRINTS",
        "USAGE": "USAGE",
        "USAGE_SUMMARY": "USAGE_SUMMARY",
        "PRIOR_USAGE": "PRIOR_USAGE",
        "DELIVERIES": "DELIVERIES",
    }
    if getattr(result, "result_kind", None) != kinds[query.query_kind]:
        raise ValueError("content response kind differs")
    if isinstance(query, ReadContentEdition):
        if (
            not isinstance(result, ContentEditionView)
            or result.composition.edition_id != query.edition_id
            or (
                query.revision_id is not None
                and result.composition.deliverable_revision_id != query.revision_id
            )
        ):
            raise ValueError("content response edition pointer differs")
    elif isinstance(query, ReadContentSection):
        if not isinstance(result, ContentSectionPage) or (
            result.edition_id,
            result.revision_id,
            result.composition_sha256,
            result.section_id,
        ) != (query.edition_id, query.revision_id, query.composition_sha256, query.section_id):
            raise ValueError("content response section pointer differs")
        if len(result.rows) > query.limit or any(
            row.position != query.after_position + i for i, row in enumerate(result.rows, 1)
        ):
            raise ValueError("content response page differs")
    elif isinstance(query, ListContentEditions):
        if not isinstance(result, ContentEditionList) or any(
            row.deliverable_id != query.deliverable_id for row in result.rows
        ):
            raise ValueError("content response product differs")
    elif isinstance(query, ReadContentHistory) and (
        not isinstance(result, ContentHistoryPage) or result.edition_id != query.edition_id
    ):
        raise ValueError("content response history differs")
    elif isinstance(query, ReadContentPrints) and (
        not isinstance(result, ContentPrintList)
        or result.edition_id != query.edition_id
        or any(row.record.scope.edition_id != query.edition_id for row in result.rows)
    ):
        raise ValueError("content response prints differ")
    elif isinstance(query, (ReadContentUsage, ReadPriorContentUsage)) and (
        not isinstance(result, (ContentUsagePage, PriorUsagePage))
        or result.query_sha256 != content_sha256(query.model_dump(mode="json"))
    ):
        raise ValueError("content response usage differs")
    elif isinstance(query, ReadContentDeliveries) and (
        not isinstance(result, ContentDeliveryList)
        or result.edition_id != query.edition_id
        or any(row.prepared.edition_id != query.edition_id for row in result.rows)
    ):
        raise ValueError("content delivery history differs")
    elif isinstance(query, ReadContentUsageSummary) and (
        not isinstance(result, ContentUsageSummary)
        or result.query_sha256 != content_sha256(query.model_dump(mode="json"))
        or tuple(row.target_index for row in result.rows) != tuple(range(len(query.targets)))
    ):
        raise ValueError("content usage summary differs")
