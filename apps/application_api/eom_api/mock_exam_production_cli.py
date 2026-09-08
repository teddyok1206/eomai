"""Pointer-only operator CLI for one resumable mock-exam production phase at a time."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from eom_api_contracts.mock_exam_execution import (
    MockExamExplicitAnalysisReviewSetV1,
    MockExamExplicitRatingSetV1,
    MockExamGraphPublicationInputV1,
)
from eom_operator_identity import ActorContext
from pydantic import BaseModel, ValidationError

from eom_api.lifespan import AppServices, build_services
from eom_api.services.mock_exam_production_composition import (
    MockExamProductionRuntime,
    build_mock_exam_production_runtime,
)

mock_exam_production_app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
DEFAULT_CHECKPOINT_ROOT = Path("/var/lib/eom-api/mock-exam-production")
_MAX_ACCESS_TOKEN_BYTES = 512
_MAX_POINTER_DOCUMENT_BYTES = 1024 * 1024
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")

AccessTokenFile = Annotated[
    Path,
    typer.Option(
        "--access-token-file",
        exists=True,
        dir_okay=False,
        resolve_path=False,
        help="Root-owned or operator-owned mode-0600 file containing one access token",
    ),
]
CheckpointRoot = Annotated[
    Path,
    typer.Option(
        "--checkpoint-root",
        file_okay=False,
        resolve_path=True,
        help="Absolute runtime checkpoint directory outside every Git worktree",
    ),
]


@dataclass(frozen=True)
class _OperatorSession:
    services: AppServices
    runtime: MockExamProductionRuntime
    actor: ActorContext


@contextmanager
def _operator_session(
    access_token_file: Path,
    checkpoint_root: Path,
) -> Iterator[_OperatorSession]:
    services = build_services()
    try:
        runtime = build_mock_exam_production_runtime(
            services,
            checkpoint_root=checkpoint_root,
        )
        at = datetime.now(UTC)
        actor = runtime.authenticator.authenticate(
            _read_access_token(access_token_file),
            request_id=f"mockexamcli_{os.urandom(12).hex()}",
            at=at,
        )
        yield _OperatorSession(services=services, runtime=runtime, actor=actor)
    finally:
        services.engine.dispose()


def _execute(
    access_token_file: Path,
    checkpoint_root: Path,
    action: Callable[[_OperatorSession], BaseModel],
) -> None:
    try:
        with _operator_session(access_token_file, checkpoint_root) as session:
            result = action(session)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        code = getattr(exc, "code", None)
        safe_code = (
            code
            if isinstance(code, str) and _ERROR_CODE.fullmatch(code)
            else ("MOCK_EXAM_PRODUCTION_COMMAND_FAILED")
        )
        typer.echo(json.dumps({"status": "FAILED", "error_code": safe_code}, sort_keys=True))
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {"status": "SUCCEEDED", "data": result.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@mock_exam_production_app.command("inspect-plan")
def inspect_plan(
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Resolve and display only the released static plan and its immutable pointers."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.inspect_plan(session.actor),
    )


@mock_exam_production_app.command("initialize")
def initialize(
    production_request_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Create or replay the sequence-zero checkpoint for one production occurrence."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.initialize(
            production_request_id,
            session.actor,
        ),
    )


@mock_exam_production_app.command("status")
def status(
    execution_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Read the current validated pointer-only checkpoint."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.get(execution_id, session.actor),
    )


@mock_exam_production_app.command("advance-items")
def advance_items(
    execution_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Reconcile the 25 independent one-Item workflows by one bounded pass."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.advance_items(
            execution_id,
            session.actor,
        ),
    )


@mock_exam_production_app.command("retire-items")
def retire_items(
    execution_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Atomically fence the exact 25-Workflow occurrence before runner restart."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.retire_items(
            execution_id,
            session.actor,
        ),
    )


@mock_exam_production_app.command("advance-analyses")
def advance_analyses(
    execution_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Reconcile exact Item-revision analyses using the released risk-policy pointer."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.advance_analyses(
            execution_id,
            session.actor,
        ),
    )


@mock_exam_production_app.command("review-analyses")
def review_analyses(
    execution_id: str,
    review_set_file: Annotated[
        Path,
        typer.Option("--review-set", exists=True, dir_okay=False, resolve_path=False),
    ],
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Apply one explicit self-hashed operator decision set to review-required analyses."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.review_analyses(
            execution_id,
            session.actor,
            _load_pointer_document(review_set_file, MockExamExplicitAnalysisReviewSetV1),
        ),
    )


@mock_exam_production_app.command("publish-graph")
def publish_graph(
    execution_id: str,
    publication_input_file: Annotated[
        Path,
        typer.Option("--publication-input", exists=True, dir_okay=False, resolve_path=False),
    ],
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Publish the exact 25-Item cohort atomically from an immutable base pointer."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.publish_graph(
            execution_id,
            session.actor,
            _load_pointer_document(
                publication_input_file,
                MockExamGraphPublicationInputV1,
            ),
        ),
    )


@mock_exam_production_app.command("publish-ratings")
def publish_ratings(
    execution_id: str,
    rating_set_file: Annotated[
        Path,
        typer.Option("--rating-set", exists=True, dir_okay=False, resolve_path=False),
    ],
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Publish the exact self-hashed 25-Item human rating set."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.publish_ratings(
            execution_id,
            session.actor,
            _load_pointer_document(rating_set_file, MockExamExplicitRatingSetV1),
        ),
    )


@mock_exam_production_app.command("advance-assembly")
def advance_assembly(
    execution_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Create/replay the unique MOCK_EXAM deliverable and exact-cohort assembly."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.advance_assembly(
            execution_id,
            session.actor,
        ),
    )


@mock_exam_production_app.command("advance-hwpx")
def advance_hwpx(
    execution_id: str,
    access_token_file: AccessTokenFile,
    checkpoint_root: CheckpointRoot = DEFAULT_CHECKPOINT_ROOT,
) -> None:
    """Create or observe the HWPX build for the pinned Assembly Revision."""

    _execute(
        access_token_file,
        checkpoint_root,
        lambda session: session.runtime.application.advance_hwpx(
            execution_id,
            session.actor,
        ),
    )


def _read_access_token(path: Path) -> str:
    payload = _read_bounded(
        path,
        _MAX_ACCESS_TOKEN_BYTES,
        required_owner=os.geteuid(),
        required_mode=0o600,
        error_code="OPERATOR_ACCESS_TOKEN_FILE_INVALID",
    )
    try:
        value = payload.decode("ascii").rstrip("\r\n")
    except UnicodeError as exc:
        raise MockExamProductionCliInputError("OPERATOR_ACCESS_TOKEN_FILE_INVALID") from exc
    if not value or "\n" in value or "\r" in value:
        raise MockExamProductionCliInputError("OPERATOR_ACCESS_TOKEN_FILE_INVALID")
    return value


def _load_pointer_document[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    try:
        payload = _read_bounded(path, _MAX_POINTER_DOCUMENT_BYTES)
        return model.model_validate_json(payload)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        raise MockExamProductionCliInputError("OPERATOR_POINTER_DOCUMENT_INVALID") from exc


def _read_bounded(
    path: Path,
    maximum_bytes: int,
    *,
    required_owner: int | None = None,
    required_mode: int | None = None,
    error_code: str = "OPERATOR_INPUT_FILE_INVALID",
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MockExamProductionCliInputError(error_code) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or (required_owner is not None and before.st_uid != required_owner)
            or (required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode)
        ):
            raise MockExamProductionCliInputError(error_code)
        payload = _read_descriptor(descriptor, before.st_size, error_code=error_code)
        if os.read(descriptor, 1):
            raise MockExamProductionCliInputError(error_code)
        after = os.fstat(descriptor)
        if _stable_file_identity(after) != _stable_file_identity(before):
            raise MockExamProductionCliInputError(error_code)
        return payload
    except OSError as exc:
        raise MockExamProductionCliInputError(error_code) from exc
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, size: int, *, error_code: str) -> bytes:
    value = bytearray()
    while len(value) < size:
        chunk = os.read(descriptor, min(64 * 1024, size - len(value)))
        if not chunk:
            break
        value.extend(chunk)
    if len(value) != size:
        raise MockExamProductionCliInputError(error_code)
    return bytes(value)


def _stable_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


class MockExamProductionCliInputError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__("operator input failed validation")
        self.code = code
