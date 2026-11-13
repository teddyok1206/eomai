"""Small closed source-read dispatcher for the existing private Catalog socket.

The stream owner calls open_document separately and forwards its validated header
and verified member. It must never serialize a stream inside a JSON response.
"""

from typing import BinaryIO, Literal

from eom_catalog_contracts.material_native_item_read import (
    MaterialNativeItemReadRequest,
    MaterialNativeItemReadResponse,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes

from eom_catalog_service.material_native_item_read import (
    MaterialNativeItemReadError,
    MaterialNativeItemReadService,
)

MATERIAL_NATIVE_READ_OPERATIONS = frozenset(
    {"GET_NATIVE_MATERIAL_ITEM_SOURCE", "GET_NATIVE_MATERIAL_ITEM_DOCUMENT"}
)


def dispatch_native_material_item_read(
    value: object, outgoing: BinaryIO, *, service: MaterialNativeItemReadService | None
) -> None:
    """Forward one authorized small source response or a verified native document stream."""
    operation: Literal["GET_NATIVE_MATERIAL_ITEM_SOURCE", "GET_NATIVE_MATERIAL_ITEM_DOCUMENT"] = (
        "GET_NATIVE_MATERIAL_ITEM_SOURCE"
    )
    document = None
    try:
        if not isinstance(value, dict) or len(canonical_json_bytes(value)) > 16 * 1024:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_REQUEST_INVALID")
        validate_contract("material-native-item-read-request-v1", value)
        request = MaterialNativeItemReadRequest.model_validate(value)
        operation = request.operation
        if service is None:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_UNAVAILABLE")
        if request.operation == "GET_NATIVE_MATERIAL_ITEM_SOURCE":
            reply = MaterialNativeItemReadResponse(
                operation=request.operation, status="OK", source=service.read_source(request)
            )
        else:
            document = service.open_document(request)
            reply = document.header
        payload = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
        if len(payload) > 256 * 1024:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_RESPONSE_TOO_LARGE")
    except Exception as error:
        if document is not None:
            document.member.stream.close()
        code = (
            error.code
            if isinstance(error, MaterialNativeItemReadError)
            else "MATERIAL_NATIVE_READ_SOURCE_INVALID"
            if isinstance(error, ValueError)
            else "MATERIAL_NATIVE_READ_UNAVAILABLE"
        )
        reply = MaterialNativeItemReadResponse(operation=operation, status="ERROR", error_code=code)
        outgoing.write(canonical_json_bytes(reply.model_dump(mode="json")) + b"\n")
        return
    outgoing.write(payload)
    if document is not None:
        try:
            for chunk in document.member.iter_chunks():
                outgoing.write(chunk)
        finally:
            document.member.stream.close()
