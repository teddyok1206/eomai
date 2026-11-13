"""Private Catalog wire framing for bounded material intake and progress reads."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from eom_catalog_contracts.material_learning_authorization import (
    MATERIAL_AUTHORIZATION_MAX_BYTES,
    MaterialLearningAuthorizationReply,
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_contracts.material_learning_intake import (
    MATERIAL_SOURCE_FORMATS,
    ControlMaterialLearningRunCommand,
    GetMaterialLearningRunQuery,
    GetMaterialLearningTaskQuery,
    ListMaterialLearningRunsQuery,
    MaterialLearningErrorResponse,
    MaterialSourceUploadCommand,
    RetryMaterialLearningRunCommand,
)
from eom_catalog_contracts.material_native_intake import parse_material_learning_create
from eom_catalog_contracts.material_native_prepare import PrepareNativeMaterialExamCommand
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.repository import IdempotencyConflict
from pydantic import BaseModel, ValidationError

from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningAuthorizationService,
)
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_read import MaterialLearningReadService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
)
from eom_catalog_service.material_learning_store import MaterialLearningStorageError
from eom_catalog_service.material_native_preparation import MaterialNativePreparationService

MATERIAL_LEARNING_OPERATIONS = frozenset(
    {
        "INGEST_MATERIAL_LEARNING_SOURCE",
        "PREPARE_NATIVE_MATERIAL_EXAM",
        "CREATE_MATERIAL_LEARNING",
        "LIST_MATERIAL_LEARNING_RUNS",
        "GET_MATERIAL_LEARNING_RUN",
        "AUTHORIZE_MATERIAL_LEARNING_INPUT",
        "CONTROL_MATERIAL_LEARNING_RUN",
        "RETRY_MATERIAL_LEARNING_RUN",
        "GET_MATERIAL_LEARNING_TASK",
    }
)


def _receive_material_file(
    incoming: BinaryIO, path: Path, *, content_length: int, sha256: str
) -> None:
    """A bounded private upload hand-off shared by original and metadata inputs."""
    digest = hashlib.sha256()
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        remaining = content_length
        while remaining:
            chunk = incoming.read(min(1024 * 1024, remaining))
            if not chunk:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UPLOAD_TRUNCATED")
            stream.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        if incoming.read(1):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_UPLOAD_EXCEEDED")
        stream.flush()
        os.fsync(stream.fileno())
    if "sha256:" + digest.hexdigest() != sha256:
        raise MaterialLearningSourceError("MATERIAL_LEARNING_UPLOAD_HASH_MISMATCH")


def dispatch_material_learning(
    value: object,
    incoming: BinaryIO,
    outgoing: BinaryIO,
    *,
    sources: MaterialLearningSourceService | None,
    intake: MaterialLearningIntakeService | None,
    reads: MaterialLearningReadService | None,
    authorizations: CatalogMaterialLearningAuthorizationService | None = None,
    native_preparation: MaterialNativePreparationService | None = None,
) -> None:
    reply: BaseModel
    try:
        if not isinstance(value, dict):
            raise ValueError("invalid request")
        operation = value.get("operation")
        if operation == "AUTHORIZE_MATERIAL_LEARNING_INPUT":
            if len(canonical_json_bytes(value)) > MATERIAL_AUTHORIZATION_MAX_BYTES:
                raise ValueError("oversized material authorization")
            request = MaterialLearningAuthorizationRequest.model_validate(value)
            try:
                if authorizations is None:
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_AUTHORIZATION_UNAVAILABLE")
                reply = authorizations.authorize(request)
            except Exception as error:
                reply = MaterialLearningAuthorizationReply(
                    status="FAILED",
                    request_sha256=content_sha256(request.model_dump(mode="json")),
                    input_sha256=None,
                    error_code="MATERIAL_LEARNING_AUTHORIZATION_FAILED"
                    if isinstance(error, (ValueError, MaterialLearningSourceError))
                    else "MATERIAL_LEARNING_AUTHORIZATION_UNAVAILABLE",
                )
        elif operation == "INGEST_MATERIAL_LEARNING_SOURCE":
            command = MaterialSourceUploadCommand.model_validate(value)
            if sources is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            sources.authorize_upload(command)
            with tempfile.TemporaryDirectory(
                prefix="material-upload.", dir=sources.settings.staging_root
            ) as directory:
                path = Path(directory) / (
                    "original" + MATERIAL_SOURCE_FORMATS[command.source_format].suffix
                )
                _receive_material_file(
                    incoming, path, content_length=command.content_length, sha256=command.sha256
                )
                reply = sources.ingest(path, command)
        elif operation == "PREPARE_NATIVE_MATERIAL_EXAM":
            native_command = PrepareNativeMaterialExamCommand.model_validate(value)
            if native_preparation is None:
                raise MaterialLearningSourceError("MATERIAL_NATIVE_PREPARATION_UNAVAILABLE")
            native_preparation.authorize_upload(native_command)
            with tempfile.TemporaryDirectory(
                prefix="material-native-upload.", dir=native_preparation.settings.staging_root
            ) as directory:
                path = Path(directory) / "metadata.xlsx"
                _receive_material_file(
                    incoming,
                    path,
                    content_length=native_command.workbook_bytes,
                    sha256=native_command.workbook_sha256,
                )
                reply = native_preparation.prepare_and_create(path, native_command)
        elif operation == "CREATE_MATERIAL_LEARNING":
            create = parse_material_learning_create(value)
            if intake is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = intake.create(create)
        elif operation == "CONTROL_MATERIAL_LEARNING_RUN":
            if intake is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = intake.control(ControlMaterialLearningRunCommand.model_validate(value))
        elif operation == "RETRY_MATERIAL_LEARNING_RUN":
            if intake is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = intake.retry(RetryMaterialLearningRunCommand.model_validate(value))
        elif operation == "LIST_MATERIAL_LEARNING_RUNS":
            list_query = ListMaterialLearningRunsQuery.model_validate(value)
            if reads is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = reads.recent(list_query)
        elif operation == "GET_MATERIAL_LEARNING_RUN":
            read_query = GetMaterialLearningRunQuery.model_validate(value)
            if reads is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = reads.inspect(read_query)
        elif operation == "GET_MATERIAL_LEARNING_TASK":
            if reads is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = reads.task(GetMaterialLearningTaskQuery.model_validate(value))
        else:
            raise ValueError("unsupported operation")
    except (MaterialLearningSourceError, MaterialLearningStorageError) as error:
        reply = MaterialLearningErrorResponse(error_code=error.code)
    except IdempotencyConflict:
        reply = MaterialLearningErrorResponse(error_code="MATERIAL_LEARNING_IDEMPOTENCY_CONFLICT")
    except (ValidationError, ValueError):
        reply = MaterialLearningErrorResponse(error_code="MATERIAL_LEARNING_REQUEST_INVALID")
    except Exception:
        # Never leak filesystem paths, database errors or untrusted file text.
        reply = MaterialLearningErrorResponse(error_code="MATERIAL_LEARNING_UNAVAILABLE")
    outgoing.write(canonical_json_bytes(reply.model_dump(mode="json")) + b"\n")
    outgoing.flush()
