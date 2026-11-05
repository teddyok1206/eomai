"""Thin private API peer adapter for saved-assembly metadata, not a second store."""

from __future__ import annotations

import logging

from eom_catalog_contracts.curated_document_assembly_library import (
    LIBRARY_RESPONSE_TYPES,
    LIBRARY_SCHEMA,
    CuratedAssemblyLibraryResponse,
    CuratedDocumentAssemblyCreateCommandV2,
    CuratedDocumentAssemblyCreateResponseV2,
    CuratedDocumentAssemblyListQueryV2,
    CuratedDocumentAssemblyListResponseV2,
    CuratedDocumentAssemblyRemoveCommandV1,
    CuratedDocumentAssemblyRemoveResponseV1,
    parse_curated_library_request,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.curated_document_assembly_item import CuratedDocumentAssemblyItemError
from eom_catalog_service.curated_document_assembly_resolution import (
    CuratedDocumentAssemblyResolutionError,
)
from eom_catalog_service.curated_document_assembly_service import (
    CuratedDocumentAssemblyError,
    CuratedDocumentAssemblyService,
)
from eom_catalog_service.curated_document_assembly_source import CuratedDocumentAssemblySourceError
from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaError

_LOGGER = logging.getLogger(__name__)


def dispatch_curated_assembly_library(
    service: CuratedDocumentAssemblyService | None, value: dict[str, object]
) -> bytes:
    """Only reached after the existing private Catalog socket API-peer check."""
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in LIBRARY_RESPONSE_TYPES:
        raise ValueError("unknown assembly library operation")

    def failure(code: str) -> CuratedAssemblyLibraryResponse:
        return LIBRARY_RESPONSE_TYPES[operation].model_validate(
            dict(operation=operation, status="ERROR", error_code=code)
            | ({"values": ()} if operation == "LIST_CURATED_DOCUMENT_ASSEMBLIES_V2" else {})
        )

    try:
        command = parse_curated_library_request(value)
    except (ValueError, SchemaError):
        result = failure("CATALOG_APPLICATION_REQUEST_INVALID")
    else:
        if service is None:
            result = failure("CATALOG_APPLICATION_UNAVAILABLE")
        else:
            actor = ActorContext(
                actor_type=ActorType.OPERATOR,
                operator_id=command.actor_id,
                session_id=command.session_id,
                request_id=command.request_id,
                authentication_time=command.authentication_time,
                permissions=frozenset(),
                source=ActorSource.APPLICATION_API,
            )
            try:
                match command:
                    case CuratedDocumentAssemblyCreateCommandV2():
                        result = CuratedDocumentAssemblyCreateResponseV2(
                            status="OK",
                            manifest=service.create(
                                command.draft, actor=actor, idempotency_key=command.idempotency_key
                            ),
                        )
                    case CuratedDocumentAssemblyListQueryV2():
                        entries, cursor = service.list_recent_titled(
                            actor=actor, limit=command.limit, cursor=command.cursor
                        )
                        result = CuratedDocumentAssemblyListResponseV2(
                            status="OK", values=entries, next_cursor=cursor
                        )
                    case CuratedDocumentAssemblyRemoveCommandV1():
                        result = CuratedDocumentAssemblyRemoveResponseV1(
                            status="OK",
                            receipt=service.remove_from_list(
                                command.assembly_id,
                                command.selection,
                                actor=actor,
                                idempotency_key=command.idempotency_key,
                            ),
                        )
            except (
                CuratedDocumentAssemblyError,
                CuratedDocumentAssemblyResolutionError,
                CuratedDocumentAssemblySourceError,
                CuratedDocumentAssemblyItemError,
                ExternalItemDocumentMediaError,
            ) as error:
                result = failure(error.code)
            except Exception as error:
                _LOGGER.error(
                    "curated assembly library failed operation=%s request_id=%s exception=%s",
                    operation,
                    command.request_id,
                    type(error).__name__,
                )
                result = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    payload = result.model_dump(mode="json")
    validate_contract(LIBRARY_SCHEMA, payload)
    return canonical_json_bytes(payload) + b"\n"
