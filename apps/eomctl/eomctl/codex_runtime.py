"""Operator presentation for non-updating checks and explicit maintenance diagnostics."""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import typer
from eom_orchestrator.capability_observer import observe_codex_cli_surface
from eom_orchestrator.codex_compatibility_maintenance import (
    assert_codex_compatibility_database_quiescent,
    assert_codex_workers_quiescent,
)
from eom_orchestrator.codex_distribution_update import check_codex_distribution_update
from eom_orchestrator.codex_runtime_compatibility import (
    prepare_codex_compatibility_matrix_request,
    prepare_codex_compatibility_request,
    run_codex_compatibility,
    validate_codex_compatibility_preflight,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.settings import Settings, SettingsError
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.codex_compatibility import (
    CodexCompatibilityRequest,
    compatibility_request_sha256,
    load_compatibility_request,
)
from eom_workflow.codex_compatibility_matrix import CompatibilityMatrix, load_compatibility_matrix
from eom_workflow.control_plane import ReasoningEffort
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

codex_runtime_app = typer.Typer(no_args_is_help=True)
_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_MATRIX_BYTES = 64 * 1024
_SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
MODEL_OPTION = typer.Option(None, "--model")
EFFORT_OPTION = typer.Option(None, "--effort")
SLOT_OPTION = typer.Option(None, "--slot")
MATRIX_FILE_OPTION = typer.Option(None, "--matrix-file", exists=True, dir_okay=False)
SOURCE_COMMIT_OPTION = typer.Option(..., "--source-commit")
OUTPUT_FILE_OPTION = typer.Option(..., "--output-file", dir_okay=False)
REQUEST_FILE_OPTION = typer.Option(..., "--request-file", exists=True, dir_okay=False)


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _source_commit(value: str) -> str:
    if _SOURCE_COMMIT_PATTERN.fullmatch(value) is None:
        raise typer.BadParameter("source commit must be the exact lowercase 40-character identity")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = member
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("non-JSON constant")


def _read_private_compatibility_json_file(path: Path, *, maximum_bytes: int) -> object:
    """Read untrusted presentation input without following links or exposing its content."""

    if not path.is_absolute():
        raise typer.BadParameter("compatibility input file must use an absolute path")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= maximum_bytes
            ):
                raise ValueError("request file boundary differs")
            payload = stream.read(maximum_bytes + 1)
            after = os.fstat(stream.fileno())
            if (
                len(payload) != before.st_size
                or len(payload) > maximum_bytes
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (before.st_uid, before.st_mode, before.st_nlink)
                != (after.st_uid, after.st_mode, after.st_nlink)
            ):
                raise ValueError("request changed during read")
        raw: object = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_constant,
        )
        return raw
    except (OSError, ValueError, JsonSchemaValidationError, RecursionError) as exc:
        raise typer.BadParameter(
            "input must be valid bounded compatibility JSON in an invoking-user-owned "
            "single-link regular file with mode 0600"
        ) from exc


def read_compatibility_request_file(path: Path) -> CodexCompatibilityRequest:
    try:
        return load_compatibility_request(
            _read_private_compatibility_json_file(path, maximum_bytes=_MAX_REQUEST_BYTES)
        )
    except (ValueError, JsonSchemaValidationError) as exc:
        raise typer.BadParameter("request must satisfy the bounded compatibility contract") from exc


def read_compatibility_matrix_file(path: Path) -> CompatibilityMatrix:
    try:
        return load_compatibility_matrix(
            _read_private_compatibility_json_file(path, maximum_bytes=_MAX_MATRIX_BYTES)
        )
    except (ValueError, JsonSchemaValidationError) as exc:
        raise typer.BadParameter("matrix must satisfy the bounded compatibility contract") from exc


def _write_request_file(path: Path, request: CodexCompatibilityRequest) -> None:
    if not path.is_absolute():
        raise typer.BadParameter("output file must use an absolute path")
    payload = (
        json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise typer.BadParameter(
            "output file must be new and safely writable; existing files remain"
        ) from exc


def _operation_failed(error: BaseException) -> NoReturn:
    code = (
        error.code
        if isinstance(error, (ControlPlaneError, PlatformError))
        else "CONTROL_COMPATIBILITY_FAILED"
    )
    _emit({"status": "FAILED", "error_code": code})
    raise typer.Exit(1)


def _command_engine() -> Engine:
    try:
        return build_engine()
    except (SettingsError, SQLAlchemyError, OSError, ValueError) as exc:
        _operation_failed(exc)


def _command_settings(source_commit: str) -> Settings:
    try:
        settings = Settings.from_environment()
    except (SettingsError, OSError, ValueError) as exc:
        _operation_failed(exc)
    if settings.runtime_source_commit != source_commit:
        _operation_failed(
            ControlPlaneError("CONTROL_COMPATIBILITY_RELEASE_MISMATCH", "installed release differs")
        )
    return settings


@codex_runtime_app.command("check-update")
def check_update() -> None:
    """Read installed CLI and official distribution metadata; never install or activate."""

    try:
        installed_version, flags = observe_codex_cli_surface()
        observation = check_codex_distribution_update(
            installed_version=installed_version,
            observed_at=datetime.now(UTC),
        )
    except (ControlPlaneError, OSError, ValueError) as exc:
        _operation_failed(exc)
        return
    _emit(
        {
            "distribution": observation.model_dump(mode="json"),
            "installed_required_flags": sorted(flags),
            "installation_changed": False,
            "model_defaults_changed": False,
        }
    )


@codex_runtime_app.command("prepare-compatibility")
def prepare_compatibility(
    model: list[str] | None = MODEL_OPTION,
    effort: list[ReasoningEffort] | None = EFFORT_OPTION,
    slot: list[str] | None = SLOT_OPTION,
    matrix_file: Path | None = MATRIX_FILE_OPTION,
    source_commit: str = SOURCE_COMMIT_OPTION,
    output_file: Path = OUTPUT_FILE_OPTION,
) -> None:
    """Stage an exact bounded diagnostic request; this command does not execute models."""

    source_commit = _source_commit(source_commit)
    matrix = None
    if matrix_file is not None:
        if model is not None or effort is not None or slot is not None:
            raise typer.BadParameter(
                "--matrix-file cannot be combined with --model/--effort/--slot"
            )
        matrix = read_compatibility_matrix_file(matrix_file)
    elif not model:
        raise typer.BadParameter("provide --model or --matrix-file")
    engine = _command_engine()
    try:
        if matrix is not None:
            request = prepare_codex_compatibility_matrix_request(
                engine, matrix=matrix, source_commit=source_commit, now=datetime.now(UTC)
            )
        else:
            request = prepare_codex_compatibility_request(
                engine,
                models=tuple(model or ()),
                reasoning_efforts=tuple(effort)
                if effort is not None
                else (ReasoningEffort.MEDIUM,),
                slot_ids=tuple(slot) if slot is not None else ("01", "02"),
                source_commit=source_commit,
                now=datetime.now(UTC),
            )
        _write_request_file(output_file, request)
        _emit(
            {
                "status": "PREPARED",
                "run_id": request.run_id,
                "request_sha256": compatibility_request_sha256(request),
                "cases_total": len(request.cases),
                "max_model_calls": request.max_model_calls,
                "expires_at": request.model_dump(mode="json")["expires_at"],
                "output_file": str(output_file),
                "model_calls": 0,
                "production_policy_changed": False,
            }
        )
    except (
        ControlPlaneError,
        PlatformError,
        SettingsError,
        SQLAlchemyError,
        JsonSchemaValidationError,
        ValueError,
    ) as exc:
        # BadParameter is deliberately handled by Typer with only our fixed message.
        _operation_failed(exc)
    finally:
        engine.dispose()


@codex_runtime_app.command("verify")
def verify(
    request_file: Path = REQUEST_FILE_OPTION,
    source_commit: str = SOURCE_COMMIT_OPTION,
) -> None:
    """Run approved sequential synthetic inference in an already quiescent maintenance window."""

    source_commit = _source_commit(source_commit)
    request = read_compatibility_request_file(request_file)
    settings = _command_settings(source_commit)
    engine = _command_engine()
    try:
        published = run_codex_compatibility(engine, request, settings=settings)
        report, artifact = published.report, published.artifact
        passed = sum(case.status == "PASS" for case in report.cases)
        failed = sum(case.status == "FAIL" for case in report.cases)
        not_run = sum(case.status == "NOT_RUN" for case in report.cases)
        report_pointer = ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.artifact_revision_id,
            member_path=artifact.primary_file,
            schema_ref="eom://schemas/workflow/codex-compatibility-report/1.0",
            media_type="application/json",
            sha256=artifact.primary_sha256,
        )
        _emit(
            {
                "status": "PASS" if passed == len(report.cases) else "NOT_ALL_PASSED",
                "run_id": report.request.run_id,
                "request_sha256": report.request_sha256,
                "source_commit": report.request.source_commit,
                "cli_version": report.runtime.cli_version,
                "cases_total": len(report.cases),
                "cases_passed": passed,
                "cases_failed": failed,
                "cases_not_run": not_run,
                "model_calls": report.model_calls,
                "report_pointer": report_pointer.model_dump(mode="json"),
                "artifact": {
                    "job_id": artifact.job_id,
                    "logical_artifact_id": artifact.artifact_id,
                    "revision_id": artifact.artifact_revision_id,
                    "member_path": artifact.primary_file,
                    "sha256": artifact.primary_sha256,
                    "manifest_sha256": artifact.manifest_sha256,
                    "schema_ref": "codex-compatibility-report/1.0",
                    "media_type": "application/json",
                },
                "educational_quality": "NOT_EVALUATED",
                "production_policy_changed": False,
            }
        )
        if failed or not_run:
            raise typer.Exit(1)
    except (
        ControlPlaneError,
        PlatformError,
        SettingsError,
        SQLAlchemyError,
        JsonSchemaValidationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_failed(exc)
    finally:
        engine.dispose()


@codex_runtime_app.command("maintenance-preflight")
def maintenance_preflight(
    request_file: Path = REQUEST_FILE_OPTION,
    source_commit: str = SOURCE_COMMIT_OPTION,
) -> None:
    """Read current work before the operator stops producers; do not acquire an execution permit."""

    source_commit = _source_commit(source_commit)
    request = read_compatibility_request_file(request_file)
    settings = _command_settings(source_commit)
    engine = _command_engine()
    try:
        validate_codex_compatibility_preflight(
            engine, request, settings=settings, now=datetime.now(UTC)
        )
        assert_codex_compatibility_database_quiescent(engine)
        assert_codex_workers_quiescent()
        _emit(
            {
                "status": "QUIESCENT",
                "run_id": request.run_id,
                "source_commit": source_commit,
                "model_calls": 0,
                "services_changed": False,
                "execution_authorized": False,
            }
        )
    except (ControlPlaneError, SQLAlchemyError, SettingsError, OSError, ValueError) as exc:
        _operation_failed(exc)
    finally:
        engine.dispose()


@codex_runtime_app.command("restoration-preflight")
def restoration_preflight(
    request_file: Path = REQUEST_FILE_OPTION,
    source_commit: str = SOURCE_COMMIT_OPTION,
) -> None:
    """Confirm no fixed native worker survives before the operator restores producers."""

    source_commit = _source_commit(source_commit)
    request = read_compatibility_request_file(request_file)
    _command_settings(source_commit)
    if request.source_commit != source_commit:
        _operation_failed(
            ControlPlaneError(
                "CONTROL_COMPATIBILITY_RELEASE_MISMATCH", "request source identity differs"
            )
        )
    try:
        # No TTL/binding/DB reauthorization: this is restoration evidence, not
        # permission to launch another model after a failed or expired request.
        assert_codex_workers_quiescent()
    except (ControlPlaneError, OSError, ValueError) as exc:
        _operation_failed(exc)
    _emit(
        {
            "status": "QUIESCENT",
            "run_id": request.run_id,
            "source_commit": source_commit,
            "model_calls": 0,
            "services_changed": False,
            "restoration_safe": True,
        }
    )
