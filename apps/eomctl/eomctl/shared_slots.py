"""Bounded operator release adapter; lifecycle and allocation live in Orchestrator."""

import getpass
import json
import re
from datetime import UTC, datetime
from typing import Annotated

import typer
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.preset_model_selection import validated_preset
from eom_orchestrator.settings import Settings
from eom_orchestrator.shared_slot_controls import (
    authorize_shared_slot_release,
    release_shared_slot_controls,
)
from eom_orchestrator.worker_systemd import require_shared_worker_units

shared_slots_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@shared_slots_app.command("release")
def release(
    baseline_revision: Annotated[list[str], typer.Option("--baseline-revision")],
    source_commit: Annotated[str, typer.Option("--source-commit")],
) -> None:
    """Use exact reviewed predecessors; no worker/model invocation or runtime restart."""
    from eom_api.build_info import get_build_info
    from eom_orchestrator.inference_transfer_control_invocation import (
        require_inference_transfer_control_owner,
    )
    from eom_orchestrator.inference_transfer_owner_http import (
        AuthenticatedInferenceTransferHttpSession,
    )
    from pydantic import SecretStr

    engine = None
    try:
        require_inference_transfer_control_owner()
        if (
            re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
            or not baseline_revision
            or any(
                re.fullmatch(r"execpresetrev_[0-9a-f]{32}", value) is None
                for value in baseline_revision
            )
        ):
            raise ControlPlaneError(
                "CONTROL_SHARED_INPUT_INVALID", "exact source and baseline pins required"
            )
        settings = Settings.from_environment()
        if (
            settings.runtime_source_commit != source_commit
            or get_build_info().source_commit != source_commit
        ):
            raise ControlPlaneError("CONTROL_SHARED_SOURCE_MISMATCH", "installed release differs")
        require_shared_worker_units()
        authentication = AuthenticatedInferenceTransferHttpSession.login_guiadmin(
            SecretStr(
                getpass.getpass("Scientific Studio guiadmin 비밀번호 (공용 슬롯 설정 발행): ")
            )
        )
        principal = authentication.read()

        def authorize(operator_id: str) -> None:
            authorize_shared_slot_release(
                authentication.read(), operator_id=operator_id, observed_at=datetime.now(UTC)
            )

        authorize(principal.operator_id)
        engine = build_engine()
        sessions = build_session_factory(engine)
        with sessions() as session:
            baselines = []
            for revision in baseline_revision:
                row = session.get(ExecutionPresetRevisionRecord, revision)
                if row is None:
                    raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "baseline is missing")
                baselines.append(validated_preset(row))
        result = release_shared_slot_controls(
            sessions,
            ControlArtifactPublisher(engine, settings),
            baselines=tuple(baselines),
            operator_id=principal.operator_id,
            source_commit=source_commit,
            created_at=datetime.now(UTC),
            authorize=authorize,
            require_installed_units=require_shared_worker_units,
        )
        typer.echo(
            json.dumps(
                {
                    "status": "SUCCEEDED",
                    "capacity_revision_id": result.capacity.capacity_policy_revision_id,
                    "preset_revision_ids": [v.preset_revision_id for v in result.drafts],
                    "model_calls": 0,
                }
            )
        )
    except ControlPlaneError as error:
        typer.echo(json.dumps({"status": "FAILED", "error_code": error.code}))
        raise typer.Exit(1) from None
    finally:
        if engine is not None:
            engine.dispose()
