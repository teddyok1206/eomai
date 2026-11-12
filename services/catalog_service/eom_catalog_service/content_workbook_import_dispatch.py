"""Private API-peer XLSX framing; no workbook bytes in JSON or command receipts."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookError,
    ContentWorkbookReply,
    PrepareContentWorkbookRequest,
    ReadContentWorkbookRequest,
    parse_content_workbook_reply,
    parse_content_workbook_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_layout import ContentPlanningConflict
from eom_catalog_service.content_workbook_import_service import ContentWorkbookImportService
from eom_catalog_service.content_workbook_reader import ContentWorkbookReadError
from eom_catalog_service.curated_document_assembly_source import CuratedDocumentAssemblySourceError

_LOG = logging.getLogger(__name__)


def dispatch_content_workbook(
    service: ContentWorkbookImportService | None,
    value: dict[str, object],
    incoming: BinaryIO,
    outgoing: BinaryIO,
) -> None:
    reply: ContentWorkbookReply
    try:
        request = parse_content_workbook_request(value)
        if service is None:
            raise ContentPlanningError("CATALOG_APPLICATION_UNAVAILABLE")
        actor = ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id=request.actor_id,
            session_id=request.session_id,
            request_id=request.request_id,
            authentication_time=request.authentication_time,
            permissions=frozenset(),
            source=ActorSource.APPLICATION_API,
        )
        if isinstance(request, PrepareContentWorkbookRequest):
            service.authorize_upload(actor)
            with tempfile.TemporaryDirectory(
                prefix="workbook-upload.", dir=service.settings.staging_root
            ) as directory:
                path = Path(directory) / "original.xlsx"
                digest = hashlib.sha256()
                with path.open("xb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    remaining = request.content_length
                    while remaining:
                        chunk = incoming.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ContentPlanningError("CONTENT_WORKBOOK_UPLOAD_TRUNCATED")
                        stream.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                    if incoming.read(1):
                        raise ContentPlanningError("CONTENT_WORKBOOK_UPLOAD_EXCEEDED")
                    stream.flush()
                    os.fsync(stream.fileno())
                if "sha256:" + digest.hexdigest() != request.sha256:
                    raise ContentPlanningError("CONTENT_WORKBOOK_UPLOAD_HASH_MISMATCH")
                reply = service.prepare(path, request, actor)
        elif isinstance(request, ReadContentWorkbookRequest):
            reply = service.read(
                request.proposal, actor=actor, offset=request.offset, limit=request.limit
            )
        else:
            reply = service.commit(
                request.proposal, actor=actor, idempotency_key=request.idempotency_key
            )
    except (
        ContentPlanningError,
        ContentWorkbookReadError,
        CuratedDocumentAssemblySourceError,
        ContentPlanningConflict,
    ) as exc:
        reply = ContentWorkbookError(error_code=exc.code)
    except TimeoutError:
        reply = ContentWorkbookError(error_code="CONTENT_WORKBOOK_UPLOAD_TIMEOUT")
    except (ValueError, SchemaError):
        reply = ContentWorkbookError(error_code="CONTENT_WORKBOOK_REQUEST_INVALID")
    except Exception as exc:
        _LOG.error(
            "workbook import failed operation=%s exception=%s",
            value.get("operation"),
            type(exc).__name__,
        )
        reply = ContentWorkbookError(error_code="CATALOG_APPLICATION_INTERNAL_ERROR")
    reply = parse_content_workbook_reply(reply.model_dump(mode="json"))
    outgoing.write(canonical_json_bytes(reply.model_dump(mode="json")) + b"\n")
    outgoing.flush()
