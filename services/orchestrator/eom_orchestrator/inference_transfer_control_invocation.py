"""Authenticated invocation of existing owner-only PREPARE and RELEASE leaves.

The official API principal is re-read at each existing publication/transaction
authorization boundary. Receipt hashes are identity evidence, never permission.
No implicit release, publication retry, alternate actor or latest substitution
is performed here.
"""

from __future__ import annotations

import os
import pwd
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from eom_api_contracts.auth import CurrentOperator
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity import PermissionKey, RoleKey
from eom_workflow.inference_transfer_bootstrap_contract import (
    InferenceTransferBootstrapCapacityPin,
    InferenceTransferBootstrapManifest,
    InferenceTransferBootstrapManifestV11,
    validate_inference_transfer_bootstrap_manifest,
    validate_inference_transfer_bootstrap_manifest_v11,
    validate_inference_transfer_reviewed_instruction,
)
from eom_workflow.inference_transfer_control_invocation import (
    InferenceTransferControlReleaseRequest,
    InferenceTransferControlReleaseRequestV11,
    InferenceTransferControlReleaseResult,
    InferenceTransferControlReleaseResultV11,
    InferenceTransferPreparedReceipt,
    InferenceTransferPreparedReceiptV11,
    parse_inference_transfer_prepared_receipt,
    parse_inference_transfer_prepared_receipt_v11,
    parse_inference_transfer_release_request,
    parse_inference_transfer_release_request_v11,
    parse_inference_transfer_release_result,
    parse_inference_transfer_release_result_v11,
    validate_inference_transfer_release_result_context,
    validate_inference_transfer_release_result_context_v11,
)
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_bootstrap import (
    PreparedInferenceTransferControls,
    prepare_inference_transfer_controls,
    prepare_inference_transfer_controls_v11,
    release_inference_transfer_controls,
    release_inference_transfer_controls_v11,
)
from eom_orchestrator.preset_model_selection import resolve_released_capacity_policy

_FRESH_AUTH_AGE = timedelta(minutes=15)
_OPERATOR = re.compile(r"operator_[0-9a-f]{32}", re.ASCII)
_SESSION = re.compile(r"apisession_[0-9a-f]{32}", re.ASCII)


class ControlPrincipalReader(Protocol):
    def read(self) -> CurrentOperator: ...


def require_inference_transfer_control_owner() -> None:
    """Check installed owner OS identity before credentials, settings or DB open."""
    try:
        actual = pwd.getpwnam("eom-workflow-runner")
        if (
            actual.pw_uid <= 0
            or os.getuid() != os.geteuid()
            or os.getgid() != os.getegid()
            or os.geteuid() != actual.pw_uid
        ):
            raise ValueError("protected owner identity differs")
    except (KeyError, OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_OWNER_IDENTITY_REQUIRED", "installed protected owner identity is required"
        ) from exc


class AuthenticatedInferenceTransferControlOwner:
    """Small application orchestration; actual auth and publisher are injected owners."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        publisher: ControlArtifactPublisher,
        principal: ControlPrincipalReader,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.publisher = publisher
        self.principal = principal
        self._now = now
        self._operator_id: str | None = None
        self._session_id: str | None = None

    def _clock(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ControlPlaneError("CONTROL_OWNER_CLOCK_INVALID", "owner clock must use UTC")
        return value

    def _current_principal(self) -> CurrentOperator:
        try:
            value = CurrentOperator.model_validate(self.principal.read().model_dump(mode="json"))
            now = self._clock()
            if (
                _OPERATOR.fullmatch(value.operator_id) is None
                or _SESSION.fullmatch(value.session_id) is None
                or RoleKey.ADMIN.value not in value.roles
                or PermissionKey.EXECUTION_PRESET_MANAGE.value not in value.effective_permissions
                or value.password_change_required
                or value.access_expires_at <= now
                or value.authenticated_at > now
                or now - value.authenticated_at > _FRESH_AUTH_AGE
                or (self._operator_id is not None and value.operator_id != self._operator_id)
                or (self._session_id is not None and value.session_id != self._session_id)
            ):
                raise ValueError("current authenticated control principal differs")
        except ControlPlaneError:
            raise
        except (ValueError, AttributeError, TypeError) as exc:
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED",
                "current fresh administrator authorization required",
            ) from exc
        if self._operator_id is None:
            self._operator_id, self._session_id = value.operator_id, value.session_id
        return value

    def _authorize(self, operator_id: str, action: Literal["PREPARE", "RELEASE"]) -> None:
        if action not in {"PREPARE", "RELEASE"}:
            raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "unsupported control action")
        self._authorize_current_principal(operator_id)

    def _authorize_current_principal(self, operator_id: str) -> None:
        principal = self._current_principal()
        if operator_id != principal.operator_id:
            raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "control principal differs")
        with self.sessions() as session:
            operator = session.get(OperatorRecord, principal.operator_id)
            roles = {
                role.role_key for _, role in active_role_assignments(session, principal.operator_id)
            }
            permissions = effective_permissions(session, principal.operator_id)
            if (
                operator is None
                or operator.status != "ACTIVE"
                or operator.deleted_at is not None
                or operator.must_change_password
                or RoleKey.ADMIN.value not in roles
                or PermissionKey.EXECUTION_PRESET_MANAGE not in permissions
            ):
                raise ControlPlaneError(
                    "CONTROL_AUTHORIZATION_REQUIRED", "current owner identity authorization denied"
                )

    def read_capacity_pin(self, revision_id: str) -> InferenceTransferBootstrapCapacityPin:
        """Read exact native metadata; no publication, reservation or activation."""
        if re.fullmatch(r"capacityrev_[0-9a-f]{32}", revision_id, re.ASCII) is None:
            raise ControlPlaneError(
                "CONTROL_CAPACITY_POINTER_INVALID", "capacity revision identity is invalid"
            )
        principal = self._current_principal()
        self._authorize_current_principal(principal.operator_id)
        with self.sessions() as session:
            capacity = resolve_released_capacity_policy(session, revision_id)
            result = InferenceTransferBootstrapCapacityPin(
                capacity_policy_id=capacity.capacity_policy_id,
                capacity_policy_revision_id=capacity.capacity_policy_revision_id,
                schema_version=capacity.schema_version,
                content_sha256=capacity.content_sha256,
            )
        self._authorize_current_principal(principal.operator_id)
        return result

    def prepare(
        self,
        manifest: InferenceTransferBootstrapManifest,
        *,
        platform_payload: bytes,
        rubric_payload: bytes,
    ) -> InferenceTransferPreparedReceipt:
        checked = validate_inference_transfer_bootstrap_manifest(manifest.model_dump(mode="json"))
        return self._prepare_checked(
            checked, platform_payload=platform_payload, rubric_payload=rubric_payload
        )

    def prepare_v11(
        self,
        manifest: InferenceTransferBootstrapManifestV11,
        *,
        platform_payload: bytes,
        rubric_payload: bytes,
    ) -> InferenceTransferPreparedReceiptV11:
        checked = validate_inference_transfer_bootstrap_manifest_v11(
            manifest.model_dump(mode="json")
        )
        receipt = self._prepare_checked(
            checked, platform_payload=platform_payload, rubric_payload=rubric_payload
        )
        if not isinstance(receipt, InferenceTransferPreparedReceiptV11):
            raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "successor receipt differs")
        return receipt

    def _prepare_checked(
        self,
        checked: InferenceTransferBootstrapManifest,
        *,
        platform_payload: bytes,
        rubric_payload: bytes,
    ) -> InferenceTransferPreparedReceipt:
        validate_inference_transfer_reviewed_instruction(
            checked, layer="PLATFORM", payload=platform_payload
        )
        validate_inference_transfer_reviewed_instruction(
            checked, layer="ROLE", payload=rubric_payload
        )
        principal = self._current_principal()
        if isinstance(checked, InferenceTransferBootstrapManifestV11):
            prepared = prepare_inference_transfer_controls_v11(
                self.sessions,
                self.publisher,
                manifest=checked,
                platform_payload=platform_payload,
                rubric_payload=rubric_payload,
                operator_id=principal.operator_id,
                observed_at=self._clock(),
                authorize_control_change=self._authorize,
            )
        else:
            prepared = prepare_inference_transfer_controls(
                self.sessions,
                self.publisher,
                manifest=checked,
                platform_payload=platform_payload,
                rubric_payload=rubric_payload,
                operator_id=principal.operator_id,
                observed_at=self._clock(),
                authorize_control_change=self._authorize,
            )
        body = {
            "schema_version": (
                "inference-transfer-prepared-receipt/1.1"
                if isinstance(checked, InferenceTransferBootstrapManifestV11)
                else "inference-transfer-prepared-receipt/1.0"
            ),
            "manifest": prepared.manifest.model_dump(mode="json"),
            "bootstrap_artifact": prepared.bootstrap_artifact.model_dump(mode="json"),
            "instruction_bundle": prepared.instruction_bundle.model_dump(mode="json"),
            "draft": prepared.draft.model_dump(mode="json"),
        }
        parser = (
            parse_inference_transfer_prepared_receipt_v11
            if isinstance(checked, InferenceTransferBootstrapManifestV11)
            else parse_inference_transfer_prepared_receipt
        )
        return parser(body | {"receipt_sha256": content_sha256(body)})

    def release(
        self, request: InferenceTransferControlReleaseRequest
    ) -> InferenceTransferControlReleaseResult:
        checked = parse_inference_transfer_release_request(request.model_dump(mode="json"))
        return self._release_checked(checked)

    def release_v11(
        self, request: InferenceTransferControlReleaseRequestV11
    ) -> InferenceTransferControlReleaseResultV11:
        checked = parse_inference_transfer_release_request_v11(request.model_dump(mode="json"))
        result = self._release_checked(checked)
        if not isinstance(result, InferenceTransferControlReleaseResultV11):
            raise ControlPlaneError("CONTROL_BOOTSTRAP_INVALID", "successor release result differs")
        return result

    def _release_checked(
        self, checked: InferenceTransferControlReleaseRequest
    ) -> InferenceTransferControlReleaseResult:
        principal = self._current_principal()
        receipt = checked.receipt
        release = (
            release_inference_transfer_controls_v11
            if isinstance(checked, InferenceTransferControlReleaseRequestV11)
            else release_inference_transfer_controls
        )
        released = release(
            self.sessions,
            self.publisher,
            prepared=PreparedInferenceTransferControls(
                receipt.manifest,
                receipt.bootstrap_artifact,
                receipt.instruction_bundle,
                receipt.draft,
            ),
            operator_id=principal.operator_id,
            released_at=self._clock(),
            authorize_control_change=self._authorize,
        )
        body = {
            "schema_version": (
                "inference-transfer-control-release-result/1.1"
                if isinstance(checked, InferenceTransferControlReleaseRequestV11)
                else "inference-transfer-control-release-result/1.0"
            ),
            "prepared_receipt_sha256": receipt.receipt_sha256,
            "preset": released.preset.model_dump(mode="json"),
            "evaluation_id": released.evaluation_id,
            "evaluation_artifact": released.evaluation_artifact.model_dump(mode="json"),
            "executed_cases": list(released.executed_cases),
            "quality_score_permille": None,
            "scientific_evaluation": released.scientific_evaluation,
            "human_transfer_evaluation": released.human_transfer_evaluation,
        }
        result: InferenceTransferControlReleaseResult
        if isinstance(checked, InferenceTransferControlReleaseRequestV11):
            result = parse_inference_transfer_release_result_v11(
                body | {"result_sha256": content_sha256(body)}
            )
            validate_inference_transfer_release_result_context_v11(checked, result)
        else:
            result = parse_inference_transfer_release_result(
                body | {"result_sha256": content_sha256(body)}
            )
            validate_inference_transfer_release_result_context(checked, result)
        return result
