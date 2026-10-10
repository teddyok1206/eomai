"""Explicit installed owner PREPARE/RELEASE; no automatic control activation."""

from __future__ import annotations

import getpass
import json
import os
import stat
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.control_artifacts import ControlArtifactPublisher, PublishedControlArtifact
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
    from eom_orchestrator.inference_transfer_human_review import (
        AuthenticatedInferenceTransferHumanReviewOwner,
    )
    from eom_orchestrator.inference_transfer_owner_http import (
        AuthenticatedInferenceTransferHttpSession,
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
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_METADATA_NOT_FOUND",
        "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH",
        "INFERENCE_TRANSFER_METADATA_POLICY_INVALID",
        "INFERENCE_TRANSFER_METADATA_REQUEST_INVALID",
        "INFERENCE_TRANSFER_METADATA_UNAVAILABLE",
        "INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED",
    }
)
_EXPERIMENT_FAILURE_CODES = frozenset(
    {
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
        "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
        "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED",
        "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_BASELINE_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
        "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE",
        "INFERENCE_TRANSFER_STAGING_UNAVAILABLE",
        "INFERENCE_TRANSFER_STAGING_REPLY_INVALID",
        "INFERENCE_TRANSFER_STAGING_BUDGET_EXCEEDED",
        "INFERENCE_TRANSFER_STAGING_QUERY_UNAVAILABLE",
        "INFERENCE_TRANSFER_STAGING_REQUEST_INVALID",
        "INFERENCE_TRANSFER_STAGING_INPUT_OR_REPLY_INVALID",
        "INFERENCE_EXPERIMENT_EXECUTION_UNAVAILABLE",
        "INFERENCE_EXPERIMENT_EXECUTION_KNOWN_FAILED",
        "INFERENCE_EXPERIMENT_EXECUTION_UNCERTAIN",
        "INFERENCE_EXPERIMENT_RESULT_INVALID",
        "INFERENCE_EXPERIMENT_COMMIT_UNCERTAIN",
        "INFERENCE_EXPERIMENT_COMMIT_RECEIPT_INVALID",
    }
)
_RUNTIME_IDENTITY = Path("/etc/eom/workflow-runtime.env")
_HUMAN_FAILURE_CODES = frozenset(
    {
        "INFERENCE_TRANSFER_HUMAN_AUTHORIZATION_REQUIRED",
        "INFERENCE_TRANSFER_HUMAN_CLOCK_INVALID",
        "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID",
        "INFERENCE_TRANSFER_HUMAN_SOURCE_CHANGED",
        "INFERENCE_TRANSFER_HUMAN_BUNDLE_MISMATCH",
        "INFERENCE_TRANSFER_HUMAN_EVALUATION_INVALID",
        "INFERENCE_TRANSFER_HUMAN_ARTIFACT_INVALID",
        "INFERENCE_TRANSFER_HUMAN_PUBLICATION_INVALID",
        "INFERENCE_TRANSFER_HUMAN_UNAVAILABLE",
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


def _owner(descriptor: int | None) -> tuple[Engine, AuthenticatedInferenceTransferControlOwner]:
    require_inference_transfer_control_owner()
    from eom_orchestrator.inference_transfer_control_auth import (
        FixedApiControlPrincipalReader,
        read_control_bearer_fd,
    )
    from eom_orchestrator.inference_transfer_control_invocation import (
        AuthenticatedInferenceTransferControlOwner,
    )

    principal_reader = (
        _session(None)
        if descriptor is None
        else FixedApiControlPrincipalReader(read_control_bearer_fd(descriptor))
    )
    engine = build_engine()
    try:
        settings = Settings.from_environment()
        return engine, AuthenticatedInferenceTransferControlOwner(
            build_session_factory(engine),
            ControlArtifactPublisher(engine, settings),
            principal_reader,
        )
    except Exception:
        engine.dispose()
        raise


def _failure(error: Exception) -> None:
    code = "CONTROL_BOOTSTRAP_UNAVAILABLE"
    if isinstance(error, ControlPlaneError) and error.code in _PUBLIC_FAILURE_CODES:
        code = error.code
    typer.echo(json.dumps({"status": "FAILED", "error_code": code}, sort_keys=True))


def _experiment_failure(error: Exception) -> None:
    # Optional types are imported only while executing these new commands.
    from eom_orchestrator.inference_transfer_experiment_execution import ExperimentExecutionError
    from eom_orchestrator.inference_transfer_snapshot_staging import (
        SnapshotReadFailure,
        SnapshotStagingError,
    )

    if isinstance(error, (ExperimentExecutionError, SnapshotReadFailure, SnapshotStagingError)):
        code = (
            error.code
            if error.code in _EXPERIMENT_FAILURE_CODES
            else "CONTROL_BOOTSTRAP_UNAVAILABLE"
        )
        typer.echo(json.dumps({"status": "FAILED", "error_code": code}, sort_keys=True))
    else:
        _failure(error)


def _session(descriptor: int | None) -> AuthenticatedInferenceTransferHttpSession:
    require_inference_transfer_control_owner()
    from eom_orchestrator.inference_transfer_control_auth import read_control_bearer_fd
    from eom_orchestrator.inference_transfer_owner_http import (
        AuthenticatedInferenceTransferHttpSession,
    )
    from pydantic import SecretStr

    if descriptor is not None:
        return AuthenticatedInferenceTransferHttpSession.from_bearer(
            read_control_bearer_fd(descriptor)
        )
    # Never permit getpass's echoing stdin fallback in an unattended command.
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "interactive TTY login required")
    with warnings.catch_warnings():
        # getpass must fail closed rather than use its echoing fallback.
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = SecretStr(getpass.getpass("guiadmin 비밀번호: "))
    return AuthenticatedInferenceTransferHttpSession.login_guiadmin(password)


def _installed_source_commit() -> str:
    """Embedded wheel identity must match the fixed root-owned runtime record."""
    from eom_api.build_info import get_build_info

    installed = get_build_info()
    descriptor = os.open(
        _RUNTIME_IDENTITY, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_gid != 0
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o644
            or not 0 < before.st_size <= 128
        ):
            raise ValueError("protected installed identity metadata differs")
        payload = os.read(descriptor, 129)
        if (
            len(payload) != before.st_size
            or _identity(before) != _identity(os.fstat(descriptor))
            or _identity(before) != _identity(os.stat(_RUNTIME_IDENTITY, follow_symlinks=False))
            or payload != f"EOM_RUNTIME_SOURCE_COMMIT={installed.source_commit}\n".encode("ascii")
        ):
            raise ValueError("protected installed identity differs")
        return installed.source_commit
    finally:
        os.close(descriptor)


def _human_owner(
    descriptor: int | None,
) -> tuple[Engine, AuthenticatedInferenceTransferHumanReviewOwner, str]:
    require_inference_transfer_control_owner()
    from eom_orchestrator.inference_transfer_human_review import (
        AuthenticatedInferenceTransferHumanReviewOwner,
    )
    from eom_orchestrator.inference_transfer_human_review_artifacts import OwnedHumanReviewArtifacts

    source_commit = _installed_source_commit()
    settings = Settings.from_environment()
    if settings.runtime_source_commit not in {None, source_commit}:
        raise ControlPlaneError(
            "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID", "installed runtime identity differs"
        )
    session = _session(descriptor)
    engine = build_engine()
    try:
        owner = AuthenticatedInferenceTransferHumanReviewOwner(
            principal=session,
            snapshots=session,
            comparisons=session,
            artifacts=OwnedHumanReviewArtifacts(engine),
            publisher=ControlArtifactPublisher(engine, settings),
        )
        return engine, owner, source_commit
    except Exception:
        engine.dispose()
        raise


def _human_failure(error: Exception) -> None:
    code = "INFERENCE_TRANSFER_HUMAN_UNAVAILABLE"
    if isinstance(error, ControlPlaneError) and error.code in (
        _HUMAN_FAILURE_CODES | _PUBLIC_FAILURE_CODES
    ):
        code = error.code
    typer.echo(json.dumps({"status": "FAILED", "error_code": code}, sort_keys=True))


def _human_publication(result: PublishedControlArtifact) -> None:
    from eom_protocol.artifact_members import ArtifactMemberPointer

    pointer = result.pointer
    member = ArtifactMemberPointer(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        member_path=pointer.logical_name,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        sha256=pointer.sha256,
    )
    typer.echo(
        canonical_json_bytes(
            {
                "status": "COMMITTED",
                "job_id": result.job_id,
                "artifact": member.model_dump(mode="json"),
                "manifest_sha256": result.manifest_sha256,
            }
        ).decode()
    )


@inference_transfer_control_app.command("human-bundle")
def publish_human_bundle(
    command_file: Annotated[Path, typer.Option("--command-file")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Publish two exact authorized sources and model hypotheses for human review."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        from eom_catalog_contracts.inference_transfer_human_review import (
            MAX_HUMAN_COMMAND_BYTES,
            parse_human_bundle_command,
        )

        try:
            command = parse_human_bundle_command(_read_json(command_file, MAX_HUMAN_COMMAND_BYTES))
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID", "closed human bundle command required"
            ) from None
        engine, owner, source_commit = _human_owner(access_token_fd)
        _human_publication(owner.publish_bundle(command, source_commit=source_commit))
    except Exception as exc:
        _human_failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


@inference_transfer_control_app.command("human-evaluate")
def publish_human_evaluation(
    command_file: Annotated[Path, typer.Option("--command-file")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Publish an explicit person's judgment; never generate human labels."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        from eom_catalog_contracts.inference_transfer_human_review import (
            MAX_HUMAN_COMMAND_BYTES,
            parse_human_record_command,
        )

        try:
            command = parse_human_record_command(_read_json(command_file, MAX_HUMAN_COMMAND_BYTES))
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID", "closed human evaluation command required"
            ) from None
        engine, owner, source_commit = _human_owner(access_token_fd)
        _human_publication(owner.publish_evaluation(command, source_commit=source_commit))
    except Exception as exc:
        _human_failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


@inference_transfer_control_app.command("human-read")
def read_human_review(
    pointer_file: Annotated[Path, typer.Option("--pointer-file")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Read an exact human bundle or record only after current owner authorization."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        from eom_catalog_contracts.inference_transfer_human_review import (
            HUMAN_REVIEW_BUNDLE_SCHEMA_REF,
            HUMAN_REVIEW_RECORD_SCHEMA_REF,
            MAX_HUMAN_COMMAND_BYTES,
        )
        from eom_protocol.artifact_members import ArtifactMemberPointer

        try:
            pointer = ArtifactMemberPointer.model_validate(
                _read_json(pointer_file, MAX_HUMAN_COMMAND_BYTES)
            )
            if (
                pointer.schema_ref
                not in {HUMAN_REVIEW_BUNDLE_SCHEMA_REF, HUMAN_REVIEW_RECORD_SCHEMA_REF}
                or pointer.member_path != "result.json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("human review pointer discriminator differs")
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID", "closed human review pointer required"
            ) from None
        engine, owner, _source_commit = _human_owner(access_token_fd)
        document = (
            owner.read_bundle(pointer)
            if pointer.schema_ref == HUMAN_REVIEW_BUNDLE_SCHEMA_REF
            else owner.read_evaluation(pointer)
        )
        typer.echo(canonical_json_bytes(document.model_dump(mode="json")).decode())
    except Exception as exc:
        _human_failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


@inference_transfer_control_app.command("inventory")
def inventory_experiment(
    prepare_file: Annotated[Path, typer.Option("--prepare-file")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Read the actual original-corpus index; no model, workspace or publication."""
    try:
        require_inference_transfer_control_owner()
        from eom_catalog_contracts.inference_transfer_snapshot import (
            MAX_SNAPSHOT_FRAME_BYTES,
            InferenceTransferSnapshotPrepareRequest,
            parse_snapshot_request,
        )
        from eom_orchestrator.inference_transfer_experiment_invocation import (
            AuthenticatedInferenceTransferExperimentOwner,
        )

        request = parse_snapshot_request(_read_json(prepare_file, MAX_SNAPSHOT_FRAME_BYTES))
        if not isinstance(request, InferenceTransferSnapshotPrepareRequest):
            raise ValueError("inventory requires PREPARE")
        result = AuthenticatedInferenceTransferExperimentOwner(_session(access_token_fd)).inventory(
            request
        )
        typer.echo(canonical_json_bytes(result.model_dump(mode="json")).decode())
    except Exception as exc:
        _experiment_failure(exc)
        raise typer.Exit(1) from None


@inference_transfer_control_app.command("metadata")
def resolve_experiment_metadata(
    request_file: Annotated[Path, typer.Option("--request-file")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Resolve a full Graph pointer from exact known pins using official authenticated HTTP."""
    try:
        require_inference_transfer_control_owner()
        from eom_catalog_contracts.inference_transfer_metadata import (
            MAX_METADATA_FRAME_BYTES,
            parse_metadata_request,
        )

        request = parse_metadata_request(_read_json(request_file, MAX_METADATA_FRAME_BYTES))
        result = _session(access_token_fd).resolve_metadata(request)
        typer.echo(canonical_json_bytes(result.model_dump(mode="json")).decode())
    except Exception as exc:
        _failure(exc)
        raise typer.Exit(1) from None


@inference_transfer_control_app.command("experiment")
def run_experiment(
    prepare_file: Annotated[Path, typer.Option("--prepare-file")],
    model_spec_file: Annotated[Path, typer.Option("--model-spec-file")],
    experiment_id: Annotated[str, typer.Option("--experiment-id")],
    experiment_revision_id: Annotated[str, typer.Option("--experiment-revision-id")],
    execution_id: Annotated[str, typer.Option("--execution-id")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """One bounded CPU experiment; completed workspace replay never relaunches CPU."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        from eom_catalog_contracts.inference_transfer_experiment import ExperimentBudget
        from eom_catalog_contracts.inference_transfer_snapshot import (
            MAX_SNAPSHOT_FRAME_BYTES,
            InferenceTransferSnapshotPrepareRequest,
            parse_snapshot_request,
        )
        from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
        from eom_catalog_contracts.validation import validate_contract
        from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
        from eom_orchestrator.inference_transfer_cpu_handoff import OWNER_ROOT
        from eom_orchestrator.inference_transfer_cpu_systemd import FixedCpuExperimentLauncher
        from eom_orchestrator.inference_transfer_experiment_artifacts import (
            compose_inference_transfer_experiment,
        )
        from eom_orchestrator.inference_transfer_experiment_invocation import (
            AuthenticatedInferenceTransferExperimentOwner,
        )
        from eom_orchestrator.inference_transfer_snapshot_staging import (
            SnapshotExperimentStageCommand,
        )

        prepare = parse_snapshot_request(_read_json(prepare_file, MAX_SNAPSHOT_FRAME_BYTES))
        if not isinstance(prepare, InferenceTransferSnapshotPrepareRequest):
            raise ValueError("experiment requires PREPARE")
        raw_model = _read_json(model_spec_file, MAX_SNAPSHOT_FRAME_BYTES)
        if not isinstance(raw_model, dict):
            raise ValueError("model specification must be a closed object")
        validate_contract("item-inference-transfer", raw_model)
        model = LocalEmbeddingModelSpec.model_validate(raw_model)
        command = SnapshotExperimentStageCommand(
            prepare,
            experiment_id,
            experiment_revision_id,
            model,
            ExperimentBudget(maximum_queries=4, top_k=8, batch_size=4, threads=4),
        )
        session = _session(access_token_fd)
        source_commit = _installed_source_commit()
        settings = Settings.from_environment()
        if settings.runtime_source_commit not in {None, source_commit}:
            raise ValueError("runtime source identity differs from installed wheel")
        engine = build_engine()
        execution = compose_inference_transfer_experiment(
            snapshot=session,
            cpu=FixedCpuExperimentLauncher(),
            publisher=ControlFileSetPublisher(engine, settings),
            workspace_root=OWNER_ROOT,
            source_commit=source_commit,
        )
        result = AuthenticatedInferenceTransferExperimentOwner(session, execution).execute(
            command,
            execution_id=execution_id,
        )
        typer.echo(
            canonical_json_bytes(
                {
                    "status": "COMMITTED",
                    "execution_id": result.execution_id,
                    "request_sha256": result.request_sha256,
                    "result_sha256": result.result_sha256,
                    "job_id": result.published.job_id,
                    "artifact": result.published.result.model_dump(mode="json"),
                    "manifest_sha256": result.published.manifest_sha256,
                    "cpu_launch_count": result.cpu_launch_count,
                    "scientific_evaluation": "NOT_EVALUATED",
                    "human_transfer_evaluation": "NOT_EVALUATED",
                }
            ).decode()
        )
    except Exception as exc:
        _experiment_failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


@inference_transfer_control_app.command("prepare")
def prepare_controls(
    manifest_file: Annotated[Path, typer.Option("--manifest-file")],
    platform_file: Annotated[Path, typer.Option("--platform-file")],
    rubric_file: Annotated[Path, typer.Option("--rubric-file")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Publish exact reviewed inputs and DRAFT only. TTY login or inherited bearer FD."""
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
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
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


@inference_transfer_control_app.command("capacity")
def read_capacity_pin(
    capacity_revision_id: Annotated[str, typer.Option("--capacity-revision-id")],
    access_token_fd: Annotated[int | None, typer.Option("--access-token-fd", min=3)] = None,
) -> None:
    """Read one exact released capacity pin using current authenticated control authority."""
    engine: Engine | None = None
    try:
        require_inference_transfer_control_owner()
        engine, owner = _owner(access_token_fd)
        pin = owner.read_capacity_pin(capacity_revision_id)
        typer.echo(canonical_json_bytes(pin.model_dump(mode="json")).decode())
    except Exception as exc:
        _failure(exc)
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()
