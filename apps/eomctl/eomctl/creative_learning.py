"""Authenticated local PREPARE adapter; no worker-start option is exposed."""

from __future__ import annotations

import getpass
import json
import os
import pwd
import re
import stat
import sys
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from eom_api_contracts.external_item_learning_start import ExternalItemLearningStartV1
from eom_catalog_service.external_item_learning_preparation_service import (
    ExternalItemLearningPreparationService,
    PreparedExternalItemLearningSource,
    PrepareExternalItemLearningCommand,
)
from eom_identity_service.auth_service import AuthService, LoginPolicy
from eom_identity_service.tokens import SessionTokenService, TokenCodec, TokenPolicy
from eom_operator_identity import ActorContext, ActorSource, ActorType
from eom_orchestrator.database import build_engine
from eom_orchestrator.external_item_learning_policy_preparation import (
    ExternalItemLearningControlInputs,
)
from eom_orchestrator.settings import Settings
from eom_workflow.compiler import compile_definition_data
from eom_workflow.control_plane import ModelCandidate, ReasoningEffort, UtcDatetime
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

learning_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


def _read_reviewed(path: Path, maximum: int) -> bytes:
    """Bounded local presentation input; paths and ownership are not operator authority."""

    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("reviewed input path is not canonical")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, pwd.getpwnam("eom").pw_uid}
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("reviewed input metadata differs")
        payload = os.read(descriptor, maximum + 1)

        def identity(value: os.stat_result) -> tuple[int, ...]:
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

        if (
            len(payload) != before.st_size
            or identity(before) != identity(os.fstat(descriptor))
            or identity(before) != identity(path.lstat())
        ):
            raise ValueError("reviewed input changed")
        return payload
    finally:
        os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate selection key")
        result[key] = value
    return result


def _selection(path: Path) -> ExternalItemLearningStartV1:
    raw = json.loads(_read_reviewed(path, 16 * 1024), object_pairs_hook=_unique_object)
    schema = json.loads(
        files("eom_api_contracts")
        .joinpath("schemas/external-item-learning-start-v1.schema.json")
        .read_text()
    )
    Draft202012Validator(schema).validate(raw)
    return ExternalItemLearningStartV1.model_validate(raw)


@learning_app.command("prepare")
def prepare_learning(
    request_file: Annotated[Path, typer.Option("--request-file")],
    config_directory: Annotated[Path, typer.Option("--config-directory")],
    definition_file: Annotated[Path, typer.Option("--definition-file")],
    source_commit: Annotated[str, typer.Option("--source-commit")],
    reviewed_at: Annotated[str, typer.Option("--reviewed-at")],
    capacity_revision_id: Annotated[str, typer.Option("--capacity-revision-id")],
    model: Annotated[str, typer.Option("--model")],
    reasoning_effort: Annotated[str, typer.Option("--reasoning-effort")],
    username: Annotated[str, typer.Option("--username")],
    idempotency_key: Annotated[str, typer.Option("--idempotency-key")],
) -> None:
    """Prepare one exact source with real Studio authentication and zero model calls.

    Run as the privileged local operator with the existing API environment loaded.
    No credentials, token files or Codex authentication are created or changed.
    """

    engine = auth_engine = auth = pair = None
    authenticated_operator_id: str | None = None
    result: dict[str, object] = {}
    failed = False
    try:
        if os.geteuid() != 0 or not sys.stdin.isatty():
            raise ValueError("privileged interactive preparation is required")
        if (
            re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
            or re.fullmatch(r"capacityrev_[0-9a-f]{32}", capacity_revision_id) is None
        ):
            raise ValueError("preparation release pins are invalid")
        selection = _selection(request_file)
        definition = compile_definition_data(
            yaml.safe_load(_read_reviewed(definition_file, 1024 * 1024)),
            str(definition_file),
            {"support"},
        )
        inputs = ExternalItemLearningControlInputs(
            definition=definition,
            platform_payload=_read_reviewed(
                config_directory / "instructions/platform.md", 64 * 1024
            ),
            role_payload=_read_reviewed(
                config_directory / "instructions/external-item-learning.md", 64 * 1024
            ),
            source_commit=source_commit,
            reviewed_at=TypeAdapter(UtcDatetime).validate_python(reviewed_at),
            capacity_revision_id=capacity_revision_id,
            candidate=ModelCandidate(
                model=model, reasoning_effort=ReasoningEffort(reasoning_effort)
            ),
        )
        command = PrepareExternalItemLearningCommand(selection, inputs, idempotency_key)
        # Optional API settings are loaded only by this explicit operating command;
        # ordinary platform/eomctl imports do not require the API application wheel.
        from eom_api.build_info import get_build_info
        from eom_api.settings import load_secrets, load_settings

        settings = Settings.from_environment()
        if (
            settings.runtime_source_commit != source_commit
            or get_build_info().source_commit != source_commit
        ):
            raise ValueError("installed preparation release differs")
        api_settings = load_settings()
        secrets = load_secrets()
        engine = build_engine()
        auth_engine = build_engine(secrets.database_url.get_secret_value())
        if (engine.url.host, engine.url.port or 5432, engine.url.database) != (
            auth_engine.url.host,
            auth_engine.url.port or 5432,
            auth_engine.url.database,
        ):
            raise ValueError("Identity and preparation databases differ")
        policy = api_settings.auth
        auth = AuthService(
            auth_engine,
            SessionTokenService(
                TokenCodec(secrets.token_hash_key.get_secret_value()),
                TokenPolicy(
                    policy.access_token_seconds,
                    policy.refresh_token_seconds,
                    policy.session_absolute_seconds,
                    policy.session_idle_seconds,
                ),
            ),
            login_policy=LoginPolicy(
                policy.login_failure_limit, policy.login_failure_window_seconds, policy.lock_seconds
            ),
        )
        password: str | None = getpass.getpass(
            f"Scientific Studio {username} 비밀번호 (창작 문항 준비 · 모델 호출 없음): "
        )
        if password is None:
            raise ValueError("interactive password input is missing")
        try:
            logged_in = auth.login(
                username=username, password=password, client_name="creative-item-preparation"
            )
            pair = logged_in.pair
            authenticated_operator_id = logged_in.operator_id
        finally:
            password = None

        def actor_provider() -> ActorContext:
            if auth is None or pair is None:
                raise ValueError("preparation authentication is missing")
            actual = auth.authenticate_access(pair.access_token)
            if (
                actual.password_change_required
                or (datetime.now(UTC) - actual.authenticated_at).total_seconds()
                > policy.fresh_auth_seconds
            ):
                raise ValueError("fresh preparation authentication is required")
            return ActorContext(
                actor_type=ActorType.OPERATOR,
                operator_id=actual.operator.operator_id,
                session_id=actual.session_id,
                request_id="creative-preparation",
                authentication_time=actual.authenticated_at,
                permissions=actual.permissions,
                source=ActorSource.APPLICATION_API,
            )

        worker_gid = pwd.getpwnam("eom-cdx-05").pw_gid
        service = ExternalItemLearningPreparationService(
            engine,
            settings=settings,
            actor_provider=actor_provider,
            worker_group_id=worker_gid,
        )
        prepared = service.prepare(command)
        result = {
            "status": "PREPARED_NOT_STARTED",
            **TypeAdapter(PreparedExternalItemLearningSource).dump_python(prepared, mode="json"),
            "model_invocations": 0,
            "model_availability": "NOT_RECHECKED",
        }
    except Exception as exc:
        code = str(getattr(exc, "code", "CREATIVE_PREPARATION_FAILED"))
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", code) is None:
            code = "CREATIVE_PREPARATION_FAILED"
        result = {"status": "FAILED", "error_code": code, "error_type": type(exc).__name__}
        failed = True
    finally:
        result["test_session_logout"] = "NOT_CREATED"
        if auth is not None and pair is not None and authenticated_operator_id is not None:
            try:
                auth.logout(pair.session_id, authenticated_operator_id)
                result["test_session_logout"] = "PASS"
            except Exception:
                result["test_session_logout"] = "FAILED"
        if auth_engine is not None:
            auth_engine.dispose()
        if engine is not None:
            engine.dispose()
    typer.echo(json.dumps(result, ensure_ascii=False))
    if failed:
        raise typer.Exit(1)
