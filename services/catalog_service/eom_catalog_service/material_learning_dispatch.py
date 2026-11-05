"""Private Catalog wire framing for bounded material intake and progress reads."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from eom_catalog_contracts.material_learning_intake import (
    MATERIAL_SOURCE_FORMATS,
    CreateMaterialLearningCommand,
    GetMaterialLearningRunQuery,
    ListMaterialLearningRunsQuery,
    MaterialLearningErrorResponse,
    MaterialSourceUploadCommand,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.repository import IdempotencyConflict
from pydantic import BaseModel, ValidationError

from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_read import MaterialLearningReadService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
)
from eom_catalog_service.material_learning_store import MaterialLearningStorageError

MATERIAL_LEARNING_OPERATIONS = frozenset(
    {
        "INGEST_MATERIAL_LEARNING_SOURCE",
        "CREATE_MATERIAL_LEARNING",
        "LIST_MATERIAL_LEARNING_RUNS",
        "GET_MATERIAL_LEARNING_RUN",
    }
)


def dispatch_material_learning(
    value: object,
    incoming: BinaryIO,
    outgoing: BinaryIO,
    *,
    sources: MaterialLearningSourceService | None,
    intake: MaterialLearningIntakeService | None,
    reads: MaterialLearningReadService | None,
) -> None:
    reply: BaseModel
    try:
        if not isinstance(value, dict):
            raise ValueError("invalid request")
        operation = value.get("operation")
        if operation == "INGEST_MATERIAL_LEARNING_SOURCE":
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
                digest = hashlib.sha256()
                with path.open("xb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    remaining = command.content_length
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
                if "sha256:" + digest.hexdigest() != command.sha256:
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_UPLOAD_HASH_MISMATCH")
                reply = sources.ingest(path, command)
        elif operation == "CREATE_MATERIAL_LEARNING":
            create = CreateMaterialLearningCommand.model_validate(value)
            if intake is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_UNAVAILABLE")
            reply = intake.create(create)
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
