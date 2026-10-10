"""Explicit installed owner PREPARE/RELEASE; no automatic control activation."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.settings import Settings
from eom_workflow.inference_transfer_bootstrap_contract import (
    MAX_TRANSFER_BOOTSTRAP_BYTES,
    MAX_TRANSFER_INSTRUCTION_BYTES,
    validate_inference_transfer_bootstrap_manifest,
)
from eom_workflow.inference_transfer_control_invocation import (
    MAX_TRANSFER_CONTROL_INVOCATION_BYTES,
    parse_inference_transfer_prepared_receipt,
    parse_inference_transfer_release_request,
)
from sqlalchemy import Engine

if TYPE_CHECKING:
    from eom_orchestrator.inference_transfer_control_invocation import (
        AuthenticatedInferenceTransferControlOwner,
    )

inference_transfer_control_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
_PUBLIC_FAILURE_CODES = frozenset(
    {
        "CONTROL_AUTHORIZATION_REQUIRED",
        "CONTROL_AUTH_SERVICE_UNAVAILABLE",
        "CONTROL_OWNER_IDENTITY_REQUIRED",
        "CONTROL_OWNER_CLOCK_INVALID",
        "CONTROL_BOOTSTRAP_UNAVAILABLE",
        "CONTROL_BOOTSTRAP_INVALID",
        "CONTROL_BOOTSTRAP_AUTHORIZATION_REQUIRED",
        "CONTROL_BOOTSTRAP_CONFLICT",
        "CONTROL_BOOTSTRAP_HISTORY_INVALID",
        "CONTROL_BOOTSTRAP_SOURCE_COMMIT_MISMATCH",
        "CONTROL_CAPACITY_POINTER_INVALID",
        "CONTROL_DOCUMENT_INVALID",
        "CONTROL_DOCUMENT_TOO_LARGE",
        "CONTROL_HASH_MISMATCH",
        "CONTROL_POINTER_UNSAFE",
        "CONTROL_POINTER_MISSING",
        "CONTROL_POINTER_NOT_APPROVED",
        "CONTROL_POINTER_STALE",
        "CONTROL_POINTER_HASH_MISMATCH",
        "CONTROL_POINTER_SCHEMA_MISMATCH",
        "CONTROL_POINTER_MEDIA_MISMATCH",
        "CONTROL_POINTER_MANIFEST_MISMATCH",
        "CONTROL_ARTIFACT_CONFLICT",
        "CONTROL_ARTIFACT_INVALID",
        "CONTROL_LOGICAL_CONFLICT",
        "CONTROL_REVISION_CONFLICT",
        "CONTROL_REVISION_NOT_RELEASED",
        "CONTROL_CURRENT_REVISION_STALE",
        "CONTROL_PRESET_RETIRED",
        "CONTROL_PRESET_DRAFT_REQUIRED",
        "CONTROL_PRESET_REVISION_MISSING",
        "CONTROL_PRESET_EVALUATION_REQUIRED",
        "CONTROL_EVALUATION_INVALID",
        "CONTROL_EVALUATION_HASH_MISMATCH",
        "CONTROL_EVALUATION_POLICY_MISMATCH",
        "CONTROL_EVALUATION_CONFLICT",
    }
)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_local_input(path: Path, maximum: int) -> bytes:
    """Materialize reviewed local input once; neither path nor ownership grants permission."""
    if not path.is_absolute():
        raise ValueError("reviewed local input must use an absolute path")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("reviewed local input metadata differs")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            member = os.read(descriptor, min(remaining, 64 * 1024))
            if not member:
                break
            chunks.append(member)
            remaining -= len(member)
        payload = b"".join(chunks)
        if (
            len(payload) != before.st_size
            or len(payload) > maximum
            or _identity(before) != _identity(os.fstat(descriptor))
            or _identity(before) != _identity(os.stat(path, follow_symlinks=False))
        ):
            raise ValueError("reviewed local input changed")
        payload.decode("utf-8")
        return payload
    finally:
        os.close(descriptor)


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = member
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON constant")


def _read_json(path: Path, maximum: int) -> object:
    return json.loads(
        _read_local_input(path, maximum),
        object_pairs_hook=_json_object,
        parse_constant=_reject_constant,
    )


def require_inference_transfer_control_owner() -> None:
    # Optional contract composition must not affect legacy CLI registration/help.
    from eom_orchestrator.inference_transfer_control_invocation import (
        require_inference_transfer_control_owner as require_owner,
    )

    require_owner()


def _owner(descriptor: int) -> tuple[Engine, AuthenticatedInferenceTransferControlOwner]:
    require_inference_transfer_control_owner()
    from eom_orchestrator.inference_transfer_control_auth import (
        FixedApiControlPrincipalReader,
        read_control_bearer_fd,
    )
    from eom_orchestrator.inference_transfer_control_invocation import (
        AuthenticatedInferenceTransferControlOwner,
    )

    bearer = read_control_bearer_fd(descriptor)
    engine = build_engine()
    try:
        settings = Settings.from_environment()
        return engine, AuthenticatedInferenceTransferControlOwner(
            build_session_factory(engine),
            ControlArtifactPublisher(engine, settings),
            FixedApiControlPrincipalReader(bearer),
        )
    except Exception:
        engine.dispose()
        raise


def _failure(error: Exception) -> None:
    code = "CONTROL_BOOTSTRAP_UNAVAILABLE"
    if isinstance(error, ControlPlaneError) and error.code in _PUBLIC_FAILURE_CODES:
        code = error.code
    typer.echo(json.dumps({"status": "FAILED", "error_code": code}, sort_keys=True))


@inference_transfer_control_app.command("prepare")
def prepare_controls(
    manifest_file: Annotated[Path, typer.Option("--manifest-file")],
    platform_file: Annotated[Path, typer.Option("--platform-file")],
    rubric_file: Annotated[Path, typer.Option("--rubric-file")],
    access_token_fd: Annotated[int, typer.Option("--access-token-fd", min=3)],
) -> None:
    """Publish exact reviewed inputs and DRAFT only. Token is read from an inherited FD."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        manifest = validate_inference_transfer_bootstrap_manifest(
            _read_json(manifest_file, MAX_TRANSFER_BOOTSTRAP_BYTES)
        )
        platform = _read_local_input(platform_file, MAX_TRANSFER_INSTRUCTION_BYTES)
        rubric = _read_local_input(rubric_file, MAX_TRANSFER_INSTRUCTION_BYTES)
        engine, owner = _owner(access_token_fd)
        receipt = owner.prepare(manifest, platform_payload=platform, rubric_payload=rubric)
        typer.echo(canonical_json_bytes(receipt.model_dump(mode="json")).decode())
    except Exception as exc:
        _failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


@inference_transfer_control_app.command("release")
def release_controls(
    receipt_file: Annotated[Path, typer.Option("--receipt-file")],
    access_token_fd: Annotated[int, typer.Option("--access-token-fd", min=3)],
) -> None:
    """Explicit NON_LIVE release. Never retry an uncertain publication automatically."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        receipt = parse_inference_transfer_prepared_receipt(
            _read_json(receipt_file, MAX_TRANSFER_CONTROL_INVOCATION_BYTES)
        )
        body = {
            "schema_version": "inference-transfer-control-release-request/1.0",
            "receipt": receipt.model_dump(mode="json"),
        }
        request = parse_inference_transfer_release_request(
            body | {"request_sha256": content_sha256(body)}
        )
        engine, owner = _owner(access_token_fd)
        result = owner.release(request)
        typer.echo(canonical_json_bytes(result.model_dump(mode="json")).decode())
    except Exception as exc:
        _failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()
