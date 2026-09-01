"""Presentation-only operator commands for legacy assessment extraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Never

import typer
from eom_catalog_contracts import LegacyItemExtractionRequest, validate_contract
from eom_catalog_service.intake_files import load_strict_json
from eom_catalog_service.legacy_item_extraction_service import (
    CreateLegacyItemExtractionCommand,
    LegacyItemExtractionApplicationService,
    LegacyItemExtractionServiceError,
)
from eom_orchestrator.database import build_engine
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

legacy_assessment_app = typer.Typer(no_args_is_help=True)
extraction_app = typer.Typer(no_args_is_help=True)
legacy_assessment_app.add_typer(extraction_app, name="extraction")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _failure(exc: LegacyItemExtractionServiceError) -> Never:
    _emit({"status": "FAILED", "error_code": exc.code})
    raise typer.Exit(1)


@extraction_app.command("create")
def extraction_create(
    request_file: Annotated[
        Path,
        typer.Option("--request-file", exists=True, dir_okay=False, resolve_path=True),
    ],
    idempotency_key: Annotated[str, typer.Option("--idempotency-key")],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    """Create one extraction from an exact reviewed request document."""

    try:
        raw_request = load_strict_json(request_file)
        validate_contract("legacy-item-extraction-request", raw_request)
        request = LegacyItemExtractionRequest.model_validate(raw_request)
        command = CreateLegacyItemExtractionCommand(
            request=request,
            idempotency_key=idempotency_key,
            requested_by=actor_id,
        )
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise typer.BadParameter("legacy item extraction request is invalid") from exc
    engine = build_engine()
    try:
        service = LegacyItemExtractionApplicationService(engine)
        try:
            result = service.create(command)
        except LegacyItemExtractionServiceError as exc:
            _failure(exc)
        _emit({"status": "SUCCEEDED", **result.as_dict()})
    finally:
        engine.dispose()


@extraction_app.command("inspect")
def extraction_inspect(
    workflow_id: Annotated[str, typer.Argument()],
) -> None:
    """Inspect only the workflow, plan, Job, and immutable receipt pointers."""

    engine = build_engine()
    try:
        service = LegacyItemExtractionApplicationService(engine)
        try:
            result = service.inspect(workflow_id)
        except LegacyItemExtractionServiceError as exc:
            _failure(exc)
        _emit({"status": "SUCCEEDED", **result.as_dict()})
    finally:
        engine.dispose()
