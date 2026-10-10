"""HTTP-facing queries and commands for the existing preset validation owner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Never

from eom_api_contracts.preset_model_selection import (
    PresetModelEvaluationRequest,
    PresetModelOptionsView,
    PresetModelValidationView,
)
from eom_operator_identity import ActorContext
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.preset_model_selection import preset_model_options, validated_preset
from eom_orchestrator.preset_model_validation import (
    enqueue_preset_model_validation,
    validation_status,
)
from sqlalchemy import Engine

from eom_api.errors import ApiError

_MISSING_CODES = frozenset({"CONTROL_PRESET_MISSING", "CONTROL_VALIDATION_MISSING"})
_CONFLICT_CODES = frozenset(
    {
        "CONTROL_PRESET_BASE_STALE",
        "CONTROL_PRESET_VERSION_STALE",
        "CONTROL_PRESET_RETIRED",
        "CONTROL_PRESET_NOT_PUBLISHED",
        "CONTROL_VALIDATION_REPLAY_CONFLICT",
        "CONTROL_PRESET_MODEL_CATALOG_REQUIRED",
        "CONTROL_PRESET_EVALUATION_REQUIRED",
    }
)


class PresetModelSelectionAdapter:
    """Keep model admission and artifact publication in their Orchestrator owner."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def options(self, preset_id: str) -> PresetModelOptionsView:
        try:
            with self.sessions() as session:
                logical = session.get(ExecutionPresetRecord, preset_id)
                if logical is None:
                    raise ControlPlaneError("CONTROL_PRESET_MISSING", "preset is unavailable")
                if logical.state != "ACTIVE":
                    raise ControlPlaneError("CONTROL_PRESET_RETIRED", "preset is retired")
                if logical.current_revision_id is None:
                    raise ControlPlaneError(
                        "CONTROL_PRESET_NOT_PUBLISHED", "preset is not published"
                    )
                row = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
                if row is None or row.preset_id != logical.preset_id or row.state != "RELEASED":
                    raise ControlPlaneError(
                        "CONTROL_PRESET_POINTER_INVALID", "current released revision is invalid"
                    )
                preset = validated_preset(row)
                candidates = preset_model_options(session, preset, observed_at=datetime.now(UTC))
                return PresetModelOptionsView.model_validate(
                    {
                        "preset_revision_id": preset.preset_revision_id,
                        "roles": [
                            {
                                "role": str(policy.role),
                                "worker_pool_key": policy.worker_pool_key,
                                "candidates": [
                                    item.model_dump(mode="json")
                                    for item in candidates.get(str(policy.role), ())
                                ],
                            }
                            for policy in preset.role_policies
                        ],
                        "catalog_is_entitlement": False,
                    }
                )
        except ControlPlaneError as exc:
            self._raise_api_error(exc)

    def enqueue(
        self,
        *,
        draft_revision_id: str,
        body: PresetModelEvaluationRequest,
        actor: ActorContext,
        expected_version: int,
        idempotency_key: str,
    ) -> PresetModelValidationView:
        try:
            with transaction(self.sessions) as session:
                command = enqueue_preset_model_validation(
                    session,
                    draft_revision_id=draft_revision_id,
                    base_revision_id=body.base_revision_id,
                    expected_version=expected_version,
                    requested_by=actor.actor_id,
                    request_key=idempotency_key,
                    requested_at=datetime.now(UTC),
                )
                return PresetModelValidationView.model_validate(
                    validation_status(session, command.validation_id)
                )
        except ControlPlaneError as exc:
            self._raise_api_error(exc)

    def status(self, validation_id: str) -> PresetModelValidationView:
        try:
            with self.sessions() as session:
                return PresetModelValidationView.model_validate(
                    validation_status(session, validation_id)
                )
        except ControlPlaneError as exc:
            self._raise_api_error(exc)

    @staticmethod
    def _raise_api_error(exc: ControlPlaneError) -> Never:
        status = 404 if exc.code in _MISSING_CODES else 409 if exc.code in _CONFLICT_CODES else 422
        raise ApiError(
            status,
            exc.code,
            "Preset model operation unavailable",
            "Refresh the execution settings and inspect the technical error code.",
        ) from exc
