#!/usr/bin/env python3
"""Source-upload and intake protocols, authored before transport/worker behavior."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from scripts.contracts.generate_material_learning_schemas import (
    BASE,
    ROOT,
    SHA,
    enum,
    identifier,
    integer,
    record,
    reference,
    sequence,
    text,
    version,
)

_TYPES = BASE + "intake-types/1.0#/$defs/"
_ACTOR = identifier("operator")
_KEY = {"type": "string", "pattern": "^[!-~]{16,128}$"}
_TIME = {"type": "string", "format": "date-time"}


def intake_ref(name: str) -> dict[str, Any]:
    return {"$ref": _TYPES + name}


def nullable(value: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [value, {"type": "null"}]}


def schemas() -> dict[str, dict[str, Any]]:
    intrinsic = record(
        member_path=text(1, 128),
        schema_ref={"type": "string", "pattern": "^eom://schemas/[A-Za-z0-9._/-]{1,220}$"},
        media_type=enum(
            "application/pdf", "application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"
        ),
        sha256=SHA,
        bytes=integer(8, 256 * 1024 * 1024),
    )
    receipt = record(
        schema_version=version("material-learning-source-receipt/1.0"),
        manifest=reference("artifactMember"),
        original=reference("artifactMember"),
        uploaded_by=_ACTOR,
        created_at=_TIME,
        original_filename=text(1, 255),
        source_format=enum("PDF", "HWP", "HWPX"),
    )
    selection = record(
        source_role=enum("MAIN", "SOLUTIONS"),
        source_upload=intake_ref("sourceReceipt"),
    )
    upload = record(
        schema_version=version("material-learning-source-upload/1.0"),
        operation=version("INGEST_MATERIAL_LEARNING_SOURCE"),
        actor_id=_ACTOR,
        original_filename=text(1, 255),
        source_format=enum("PDF", "HWP", "HWPX"),
        media_type=enum(
            "application/pdf", "application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"
        ),
        content_length=integer(8, 256 * 1024 * 1024),
        sha256=SHA,
        rights_confirmed={"const": True},
        idempotency_key=_KEY,
    )
    source_manifest = record(
        schema_version=version("material-learning-source-manifest/1.0"),
        uploaded_by=_ACTOR,
        original_filename=text(1, 255),
        source_format=enum("PDF", "HWP", "HWPX"),
        rights_confirmed={"const": True},
        original=intake_ref("sourceMember"),
    )
    create = record(
        schema_version=version("material-learning-create/1.0"),
        operation=version("CREATE_MATERIAL_LEARNING"),
        actor_id=_ACTOR,
        idempotency_key=_KEY,
        upload={"$ref": BASE + "upload/1.0"},
        sources=sequence(intake_ref("selectedSource"), 1, 2),
    )
    manifest = record(
        schema_version=version("material-learning-intake/1.0"),
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        requested_by=_ACTOR,
        request_sha256=SHA,
        upload={"$ref": BASE + "upload/1.0"},
        sources=sequence(intake_ref("selectedSource"), 1, 2),
        rights_attestation=reference("artifactMember"),
    )
    accepted = record(
        schema_version=version("material-learning-acceptance/1.0"),
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        run_id=identifier("materialrun"),
        request_sha256=SHA,
        replayed={"type": "boolean"},
    )
    error = record(
        schema_version=version("material-learning-error/1.0"),
        status=version("ERROR"),
        error_code={"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,127}$"},
    )
    run_state = enum(
        "RECEIVED",
        "PREPARING",
        "DISCOVERING",
        "PROCESSING",
        "WAITING_FOR_CAPACITY",
        "PAUSED",
        "COMPLETED",
        "COMPLETED_WITH_EXCEPTIONS",
        "FAILED",
        "CANCELLED",
    )
    task_state = enum(
        "PENDING",
        "PREPARING",
        "READY",
        "RUNNING",
        "RESULT_READY",
        "REGISTERED",
        "ANALYZING",
        "PUBLISHING",
        "GRAPH_READY",
        "COMPLETED",
        "EXCEPTION",
        "FAILED",
        "CANCELLED",
    )
    count = record(state=task_state, count=integer(0, 1_000_000))
    summary = record(
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        run_id=identifier("materialrun"),
        title=text(1, 200),
        material_kind=enum("TEXTBOOK", "REFERENCE_BOOK", "WORKBOOK", "MOCK_EXAM", "OTHER"),
        state=run_state,
        task_counts=sequence(intake_ref("taskCount"), 0, 13),
        error_code=nullable(text(3, 128)),
        created_at=_TIME,
        updated_at=_TIME,
    )
    task = record(
        task_id=identifier("materialtask"),
        ordinal=integer(1, 1_000_000),
        task_kind=enum("DISCOVER", "EXPLANATION", "QUESTION"),
        state=task_state,
        workflow_id=nullable(identifier("workflow")),
        item_revision_id=nullable(identifier("itemrev")),
        analysis_run_id=nullable(identifier("analysisrun")),
        graph_snapshot_revision_id=nullable(identifier("graphrev")),
        error_code=nullable(text(3, 128)),
    )
    values = {
        "intake-types": {
            "$defs": {
                "sourceMember": intrinsic,
                "sourceReceipt": receipt,
                "selectedSource": selection,
                "taskCount": count,
                "runSummary": summary,
                "taskSummary": task,
            }
        },
        "source-upload": upload,
        "source-manifest": source_manifest,
        "source-receipt": intake_ref("sourceReceipt"),
        "create": create,
        "intake": manifest,
        "acceptance": accepted,
        "error": error,
        "run-query": {
            "oneOf": [
                record(
                    schema_version=version("material-learning-run-query/1.0"),
                    operation=version("LIST_MATERIAL_LEARNING_RUNS"),
                    actor_id=_ACTOR,
                    limit=integer(1, 50),
                ),
                record(
                    schema_version=version("material-learning-run-query/1.0"),
                    operation=version("GET_MATERIAL_LEARNING_RUN"),
                    actor_id=_ACTOR,
                    run_id=identifier("materialrun"),
                    after_ordinal=integer(0, 1_000_000),
                    limit=integer(1, 100),
                ),
            ]
        },
        "run-list": record(
            schema_version=version("material-learning-run-list/1.0"),
            runs=sequence(intake_ref("runSummary"), 0, 50),
        ),
        "run-detail": record(
            schema_version=version("material-learning-run-detail/1.0"),
            run=intake_ref("runSummary"),
            tasks=sequence(intake_ref("taskSummary"), 0, 100),
            next_ordinal=nullable(integer(1, 1_000_000)),
        ),
    }
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": BASE + name + "/1.0",
            "title": f"EOM material learning {name} 1.0",
            **value,
        }
        for name, value in values.items()
    }


def main() -> None:
    for name, document in schemas().items():
        payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        filename = f"material-learning-{name}-v1.schema.json"
        for directory in (
            ROOT / "schemas/material-learning",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning",
        ):
            (directory / filename).write_bytes(payload)
        print(f"material-learning-{name}-v1 sha256:{hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
