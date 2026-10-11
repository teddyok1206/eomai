"""Official guiadmin session rotation, reads and explicit non-retried submissions."""

from __future__ import annotations

import http.client
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from eom_api_contracts.assessment_learning import AssessmentLearningCorpusViewV2
from eom_api_contracts.auth import CurrentOperator, LoginRequest, RefreshRequest, TokenPair
from eom_api_contracts.common import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.control_plane import ExecutionPresetView
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
    parse_pair_submit_request,
    parse_workflow_read_request,
    parse_workflow_read_result,
    validate_workflow_read_result_context,
)
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_pair_submit_request_v11,
    parse_workflow_read_request_v11,
    parse_workflow_read_result_v11,
    validate_workflow_read_result_context_v11,
)
from eom_catalog_contracts.inference_transfer_metadata import (
    METADATA_ERRORS,
    InferenceTransferMetadataResolveRequest,
    InferenceTransferMetadataResolveResult,
    parse_metadata_request,
    parse_metadata_result,
    validate_metadata_result,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    MAX_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    parse_snapshot_request,
    parse_snapshot_result,
    validate_snapshot_authorize_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result_context,
)
from eom_catalog_contracts.inference_transfer_snapshot_timing import (
    DEFAULT_SNAPSHOT_TIMEOUT_SECONDS,
    SnapshotPhase,
    snapshot_phase_deadlines,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey, RoleKey
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import SecretStr

from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_control_auth import (
    FixedApiControlPrincipalReader,
    require_fixed_api_peer_socket,
)
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadFailure

_HOST, _PORT = "127.0.0.1", 8765
_LOGIN = "/api/v1/auth/login"
_REFRESH = "/api/v1/auth/refresh"
_REFRESH_MARGIN = timedelta(seconds=180)
_SNAPSHOT = "/api/v1/knowledge/inference-transfer/snapshot"
_METADATA = "/api/v1/knowledge/inference-transfer/metadata"
_ORIGINAL_CORPUS = "/api/v1/assessment-learning-corpus"
_EXECUTION_PRESETS = "/api/v1/execution-presets"
_COMPARISONS = "/api/v1/knowledge/inference-transfer/comparisons"
_COMPARISONS_V11 = _COMPARISONS + "/v1.1"
_COMPARISON_WORKFLOWS = "/api/v1/knowledge/inference-transfer/workflows/"
_COMPARISON_READ_TARGET = re.compile(
    re.escape(_COMPARISON_WORKFLOWS)
    + r"workflow_[0-9a-f]{32}\?mode=(?:STATUS_ONLY|CANONICAL_RESULT)",
    re.ASCII,
)
_COMPARISON_READ_TARGET_V11 = re.compile(
    re.escape(_COMPARISON_WORKFLOWS)
    + r"workflow_[0-9a-f]{32}/v1\.1\?mode=(?:STATUS_ONLY|CANONICAL_RESULT)",
    re.ASCII,
)
_IDEMPOTENCY_KEY = re.compile(r"[!-~]{16,128}", re.ASCII)
_WORKFLOW_ID = re.compile(r"workflow_[0-9a-f]{32}", re.ASCII)
_COMMAND_ID = re.compile(r"wfcmd_[0-9a-f]{32}", re.ASCII)
_REQUEST_TARGETS = frozenset(
    {
        ("POST", _LOGIN),
        ("POST", _REFRESH),
        ("POST", _SNAPSHOT),
        ("POST", _METADATA),
        ("POST", _COMPARISONS),
        ("POST", _COMPARISONS_V11),
        ("GET", _ORIGINAL_CORPUS),
        ("GET", _EXECUTION_PRESETS),
    }
)
_MAX_ENVELOPE_BYTES = 4 * 1024**2
_LOGIN_RESPONSE = SingleResponse[TokenPair]
_LOGIN_VALIDATOR = Draft202012Validator(
    _LOGIN_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_SNAPSHOT_RESPONSE = SingleResponse[InferenceTransferSnapshotResult]
_SNAPSHOT_VALIDATOR = Draft202012Validator(
    _SNAPSHOT_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_METADATA_RESPONSE = SingleResponse[InferenceTransferMetadataResolveResult]
_METADATA_VALIDATOR = Draft202012Validator(
    _METADATA_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_ORIGINAL_CORPUS_RESPONSE = SingleResponse[AssessmentLearningCorpusViewV2]
_ORIGINAL_CORPUS_VALIDATOR = Draft202012Validator(
    _ORIGINAL_CORPUS_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_EXECUTION_PRESETS_RESPONSE = ListResponse[ExecutionPresetView]
_EXECUTION_PRESETS_VALIDATOR = Draft202012Validator(
    _EXECUTION_PRESETS_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_PAIR_SUBMIT_RESPONSE = SingleResponse[CommandResult]
_PAIR_SUBMIT_VALIDATOR = Draft202012Validator(
    _PAIR_SUBMIT_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_COMPARISON_READ_RESPONSE = SingleResponse[InferenceTransferWorkflowReadResult]
_COMPARISON_READ_VALIDATOR = Draft202012Validator(
    _COMPARISON_READ_RESPONSE.model_json_schema(), format_checker=FormatChecker()
)
_COMPARISON_READ_RESPONSE_V11 = SingleResponse[InferenceTransferWorkflowReadResultV11]
_COMPARISON_READ_VALIDATOR_V11 = Draft202012Validator(
    _COMPARISON_READ_RESPONSE_V11.model_json_schema(), format_checker=FormatChecker()
)
_COMPARISON_ERRORS = frozenset(
    {
        "API_IDEMPOTENCY_IN_PROGRESS",
        "API_IDEMPOTENCY_CONFLICT",
        "API_REQUEST_INVALID",
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SUBMISSION_INVALID",
        "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
        "INFERENCE_TRANSFER_NOT_READY",
        "INFERENCE_TRANSFER_CONTRACT_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
        "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
        "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND",
        "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
        "INFERENCE_TRANSFER_WORKFLOW_CHANGED",
        "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE",
        "INFERENCE_TRANSFER_RESULT_INVALID",
        "INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED",
        "CONTROL_PRESET_NOT_PUBLISHED",
        "CONTROL_PRESET_POINTER_INVALID",
        "CONTROL_PRESET_MODEL_UNAVAILABLE",
        "CONTROL_PROTOCOL_MISSING",
        "CONTROL_PLAN_CONFLICT",
        "CONTROL_PLAN_POLICY_MISMATCH",
        "CONTROL_TRANSFER_CONTEXT_INVALID",
        "CONTROL_TRANSFER_RUBRIC_INVALID",
    }
)
_ACTOR = re.compile(r"operator_[0-9a-f]{32}", re.ASCII)
_SESSION = re.compile(r"apisession_[0-9a-f]{32}", re.ASCII)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate response member")
        value[key] = member
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON response")


def _request(
    method: Literal["GET", "POST"],
    path: str,
    body: bytes | Callable[[], bytes] | None,
    *,
    bearer: SecretStr | None = None,
    idempotency_key: str | None = None,
    snapshot_phase: SnapshotPhase | None = None,
) -> tuple[int, object]:
    fixed_target = (method, path) in _REQUEST_TARGETS or (
        method == "GET"
        and (
            _COMPARISON_READ_TARGET.fullmatch(path) is not None
            or _COMPARISON_READ_TARGET_V11.fullmatch(path) is not None
        )
    )
    is_submission = method == "POST" and path in {_COMPARISONS, _COMPARISONS_V11}
    if (
        not fixed_target
        or (method == "GET" and body is not None)
        or (is_submission and (bearer is None or idempotency_key is None))
        or (not is_submission and idempotency_key is not None)
        or (snapshot_phase is not None and (method, path) != ("POST", _SNAPSHOT))
        or (idempotency_key is not None and _IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None)
    ):
        raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", "fixed request unavailable")
    try:
        timeout = (
            DEFAULT_SNAPSHOT_TIMEOUT_SECONDS
            if snapshot_phase is None
            else snapshot_phase_deadlines(snapshot_phase).owner_http_seconds
        )
    except ValueError:
        raise ControlPlaneError(
            "CONTROL_AUTH_SERVICE_UNAVAILABLE", "fixed snapshot phase unavailable"
        ) from None
    connection = http.client.HTTPConnection(_HOST, _PORT, timeout=timeout)
    try:
        connection.connect()
        if connection.sock is None:
            raise ValueError("fixed socket unavailable")
        require_fixed_api_peer_socket(connection.sock)
        headers = {
            "Accept": "application/json",
            "Connection": "close",
        }
        payload = body() if callable(body) else body
        if method == "POST":
            if payload is None or not 0 < len(payload) <= MAX_SNAPSHOT_FRAME_BYTES:
                raise ValueError("fixed request exceeds bound")
            headers["Content-Type"] = "application/json"
        if bearer is not None:
            headers["Authorization"] = "Bearer " + bearer.get_secret_value()
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        if response.getheader("Content-Type", "").split(";")[0].strip().lower() not in {
            "application/json",
            "application/problem+json",
        }:
            raise ValueError("fixed response unavailable")
        payload = response.read(_MAX_ENVELOPE_BYTES + 1)
        if not payload or len(payload) > _MAX_ENVELOPE_BYTES:
            raise ValueError("fixed response exceeds bound")
        value = json.loads(
            payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        return response.status, value
    except Exception:
        # Validation/network exceptions may carry secret-bearing input/response.
        raise ControlPlaneError(
            "CONTROL_AUTH_SERVICE_UNAVAILABLE", "official request unavailable"
        ) from None
    finally:
        connection.close()


def _post(
    path: str,
    body: bytes | Callable[[], bytes],
    *,
    bearer: SecretStr | None = None,
    snapshot_phase: SnapshotPhase | None = None,
) -> tuple[int, object]:
    return _request("POST", path, body, bearer=bearer, snapshot_phase=snapshot_phase)


def _get(path: str, *, bearer: SecretStr) -> tuple[int, object]:
    return _request("GET", path, None, bearer=bearer)


class AuthenticatedInferenceTransferHttpSession:
    """Session identity is captured from /me, not a caller-supplied actor string."""

    def __init__(self, bearer: SecretStr, *, refresh: SecretStr | None = None) -> None:
        self._reader = FixedApiControlPrincipalReader(bearer)
        self._bearer, self._refresh = bearer, refresh
        self._operator_id: str | None = None
        self._session_id: str | None = None
        self._authenticated_at: datetime | None = None
        self._access_expires_at: datetime | None = None
        self._refresh_failed = False

    @classmethod
    def login_guiadmin(cls, password: SecretStr) -> AuthenticatedInferenceTransferHttpSession:
        request = LoginRequest(
            username="guiadmin", password=password, client_name="EOM inference transfer owner"
        )

        # SecretStr's JSON dump is intentionally masked: materialize only at this
        # explicit verified HTTP boundary, never in metadata or presentation.
        def login_body() -> bytes:
            return canonical_json_bytes(
                {
                    "username": request.username,
                    "password": request.password.get_secret_value(),
                    "client_name": request.client_name,
                }
            )

        status, raw = _post(_LOGIN, login_body)
        if status in {401, 403, 429}:
            raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "actual login denied")
        try:
            if status != 200:
                raise ValueError("login unavailable")
            _LOGIN_VALIDATOR.validate(raw)
            tokens = _LOGIN_RESPONSE.model_validate(raw).data
            bearer, refresh = SecretStr(tokens.access_token), SecretStr(tokens.refresh_token)
            value = cls(bearer, refresh=refresh)
            principal = value.read()
            if tokens.session_id != principal.session_id:
                raise ValueError("login session differs")
            return value
        except ControlPlaneError:
            raise
        except Exception:
            raise ControlPlaneError(
                "CONTROL_AUTH_SERVICE_UNAVAILABLE", "actual login reply invalid"
            ) from None

    @classmethod
    def from_bearer(cls, bearer: SecretStr) -> AuthenticatedInferenceTransferHttpSession:
        value = cls(bearer)
        value.read()
        return value

    def _validated_principal(self, raw: CurrentOperator) -> CurrentOperator:
        value = CurrentOperator.model_validate(raw.model_dump(mode="json"))
        now = datetime.now(UTC)
        if (
            value.username != "guiadmin"
            or _ACTOR.fullmatch(value.operator_id) is None
            or _SESSION.fullmatch(value.session_id) is None
            or value.password_change_required
            or value.access_expires_at <= now
            or value.authenticated_at > now
            or (self._operator_id is not None and value.operator_id != self._operator_id)
            or (self._session_id is not None and value.session_id != self._session_id)
            or (
                self._authenticated_at is not None
                and value.authenticated_at != self._authenticated_at
            )
        ):
            raise ValueError("actual session changed or unavailable")
        return value

    def _refresh_if_due(self) -> CurrentOperator | None:
        if self._refresh_failed:
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED", "session renewal requires a new login"
            )
        if (
            self._refresh is None
            or self._access_expires_at is None
            or self._access_expires_at - datetime.now(UTC) > _REFRESH_MARGIN
        ):
            return None

        # Consumption may commit even when HTTP times out. Never reuse this token
        # after an unknown outcome or install new secrets before independent /me.
        self._refresh_failed = True
        try:
            request = RefreshRequest(refresh_token=self._refresh)

            def refresh_body() -> bytes:
                return canonical_json_bytes(
                    {"refresh_token": request.refresh_token.get_secret_value()}
                )

            status, raw = _post(_REFRESH, refresh_body)
            if status in {401, 403, 429}:
                raise ControlPlaneError(
                    "CONTROL_AUTHORIZATION_REQUIRED", "actual session renewal denied"
                )
            if status != 200:
                raise ValueError("session renewal unavailable")
            _LOGIN_VALIDATOR.validate(raw)
            tokens = _LOGIN_RESPONSE.model_validate(raw).data
            now = datetime.now(UTC)
            if (
                tokens.session_id != self._session_id
                or tokens.password_change_required
                or tokens.access_expires_at - now <= _REFRESH_MARGIN
                or tokens.refresh_expires_at <= now
                or tokens.access_token == self._bearer.get_secret_value()
                or tokens.refresh_token == self._refresh.get_secret_value()
            ):
                raise ValueError("renewed session differs or expires too soon")
            bearer, refresh = SecretStr(tokens.access_token), SecretStr(tokens.refresh_token)
            # Validate the next refresh request before committing its credential.
            RefreshRequest(refresh_token=refresh)
            reader = FixedApiControlPrincipalReader(bearer)
            principal = self._validated_principal(reader.read())
            if principal.access_expires_at != tokens.access_expires_at:
                raise ValueError("renewed bearer expiry differs")
            self._reader, self._bearer, self._refresh = reader, bearer, refresh
            self._access_expires_at = principal.access_expires_at
            self._refresh_failed = False
            return principal
        except ControlPlaneError as exc:
            raise ControlPlaneError(
                exc.code
                if exc.code
                in {"CONTROL_AUTHORIZATION_REQUIRED", "CONTROL_AUTH_SERVICE_UNAVAILABLE"}
                else "CONTROL_AUTH_SERVICE_UNAVAILABLE",
                "official session renewal unavailable",
            ) from None
        except Exception:
            raise ControlPlaneError(
                "CONTROL_AUTH_SERVICE_UNAVAILABLE", "official session renewal reply invalid"
            ) from None

    def read(self) -> CurrentOperator:
        try:
            value = self._refresh_if_due()
            if value is None:
                value = self._validated_principal(self._reader.read())
            if self._operator_id is None:
                self._operator_id, self._session_id = value.operator_id, value.session_id
                self._authenticated_at = value.authenticated_at
            self._access_expires_at = value.access_expires_at
            return value
        except ControlPlaneError as exc:
            raise ControlPlaneError(
                exc.code
                if exc.code
                in {"CONTROL_AUTHORIZATION_REQUIRED", "CONTROL_AUTH_SERVICE_UNAVAILABLE"}
                else "CONTROL_AUTH_SERVICE_UNAVAILABLE",
                "official current guiadmin session unavailable",
            ) from None
        except Exception:
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED", "current guiadmin session required"
            ) from None

    def _require_read_permission(self, permission: PermissionKey) -> None:
        principal = self.read()
        if (
            RoleKey.ADMIN.value not in principal.roles
            or permission.value not in principal.effective_permissions
        ):
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED", "current official read permission required"
            )

    def _read_official(self, path: str, permission: PermissionKey) -> object:
        self._require_read_permission(permission)
        status, raw = _get(path, bearer=self._bearer)
        if status in {401, 403}:
            raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "official read denied")
        if status != 200:
            raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", "official read unavailable")
        return raw

    def read_original_corpus(self) -> AssessmentLearningCorpusViewV2:
        """Read the official PDF-backed corpus projection, not a textbook substitute."""
        try:
            raw = self._read_official(_ORIGINAL_CORPUS, PermissionKey.KNOWLEDGE_ANALYSIS_READ)
            _ORIGINAL_CORPUS_VALIDATOR.validate(raw)
            result = _ORIGINAL_CORPUS_RESPONSE.model_validate(raw).data
            self._require_read_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ)
            return result
        except ControlPlaneError:
            raise
        except Exception:
            raise ControlPlaneError(
                "CONTROL_AUTH_SERVICE_UNAVAILABLE", "official original corpus reply invalid"
            ) from None

    def read_execution_presets(self) -> ListResponse[ExecutionPresetView]:
        """Preserve the official listing; choose and pin an exact revision outside transport.

        The official API owns fresh-auth enforcement. This read neither chooses
        the latest revision nor grants model availability or execution approval.
        """
        try:
            raw = self._read_official(_EXECUTION_PRESETS, PermissionKey.EXECUTION_PRESET_READ)
            _EXECUTION_PRESETS_VALIDATOR.validate(raw)
            result = _EXECUTION_PRESETS_RESPONSE.model_validate(raw)
            self._require_read_permission(PermissionKey.EXECUTION_PRESET_READ)
            return result
        except ControlPlaneError:
            raise
        except Exception:
            raise ControlPlaneError(
                "CONTROL_AUTH_SERVICE_UNAVAILABLE", "official execution preset reply invalid"
            ) from None

    def _comparison_principal(
        self,
        permission: PermissionKey,
        selection: InferenceTransferPairSubmitRequest | InferenceTransferPairSubmitRequestV11,
    ) -> CurrentOperator:
        principal = self.read()
        required = {
            permission.value,
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        }
        if "PAST_EXAM" in selection.snapshot_prepare.source_classes:
            required.add(PermissionKey.CONTENT_INTAKE_READ.value)
        if not required.issubset(principal.effective_permissions):
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED", "current comparison permission required"
            )
        return principal

    @staticmethod
    def _comparison_failure(status: int, raw: object, fallback: str) -> None:
        if status in {401, 403}:
            raise ControlPlaneError("CONTROL_AUTHORIZATION_REQUIRED", "comparison denied")
        code = raw.get("error_code") if isinstance(raw, dict) else None
        raise ControlPlaneError(
            code if isinstance(code, str) and code in _COMPARISON_ERRORS else fallback,
            "official comparison operation unavailable",
        )

    def submit_pair(
        self, selection: InferenceTransferPairSubmitRequest, *, idempotency_key: str
    ) -> CommandResult:
        if not isinstance(selection, InferenceTransferPairSubmitRequest):
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_SUBMISSION_INVALID", "exact comparison generation required"
            )
        return self._submit_pair(selection, idempotency_key=idempotency_key)

    def submit_pair_v11(
        self, selection: InferenceTransferPairSubmitRequestV11, *, idempotency_key: str
    ) -> CommandResult:
        if not isinstance(selection, InferenceTransferPairSubmitRequestV11):
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_SUBMISSION_INVALID", "exact comparison generation required"
            )
        return self._submit_pair(selection, idempotency_key=idempotency_key)

    def _submit_pair(
        self,
        selection: InferenceTransferPairSubmitRequest | InferenceTransferPairSubmitRequestV11,
        *,
        idempotency_key: str,
    ) -> CommandResult:
        """Submit once with the caller's retained key; never automatically retry a POST.

        UNCERTAIN means the server may have committed. The caller must retain
        this exact selection/key for explicit current-authorized replay; a new
        key or this client-side successful receipt never grants source authority.
        """
        try:
            selection = (
                parse_pair_submit_request_v11(selection.model_dump(mode="json"))
                if isinstance(selection, InferenceTransferPairSubmitRequestV11)
                else parse_pair_submit_request(selection.model_dump(mode="json"))
            )
            if _IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
                raise ValueError("invalid idempotency header")
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_SUBMISSION_INVALID", "exact comparison submission required"
            ) from None
        principal = self._comparison_principal(PermissionKey.WORKFLOW_START, selection)
        try:
            status, raw = _request(
                "POST",
                _COMPARISONS_V11
                if isinstance(selection, InferenceTransferPairSubmitRequestV11)
                else _COMPARISONS,
                canonical_json_bytes(selection.model_dump(mode="json")),
                bearer=self._bearer,
                idempotency_key=idempotency_key,
            )
        except ControlPlaneError:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN",
                "submission outcome unknown; retain exact input and key",
            ) from None
        if status != 202:
            self._comparison_failure(status, raw, "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN")
        try:
            _PAIR_SUBMIT_VALIDATOR.validate(raw)
            result = _PAIR_SUBMIT_RESPONSE.model_validate(raw).data
            if (
                result.resource_type != "workflow"
                or result.status != "ACCEPTED"
                or _WORKFLOW_ID.fullmatch(result.resource_id) is None
                or _COMMAND_ID.fullmatch(result.command_id) is None
                or result.status_url
                != (
                    _COMPARISON_WORKFLOWS
                    + result.resource_id
                    + (
                        "/v1.1"
                        if isinstance(selection, InferenceTransferPairSubmitRequestV11)
                        else ""
                    )
                )
            ):
                raise ValueError("comparison command lineage differs")
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN",
                "submission reply invalid; retain exact input and key",
            ) from None
        current = self._comparison_principal(PermissionKey.WORKFLOW_START, selection)
        if set(current.roles) != set(principal.roles):
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED", "current comparison role context changed"
            )
        return result

    def read_comparison(
        self,
        query: InferenceTransferWorkflowReadRequest,
        *,
        selection: InferenceTransferPairSubmitRequest,
    ) -> InferenceTransferWorkflowReadResult:
        if not isinstance(query, InferenceTransferWorkflowReadRequest):
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
                "exact comparison generation required",
            )
        return cast(
            InferenceTransferWorkflowReadResult, self._read_comparison(query, selection=selection)
        )

    def read_comparison_v11(
        self,
        query: InferenceTransferWorkflowReadRequestV11,
        *,
        selection: InferenceTransferPairSubmitRequestV11,
    ) -> InferenceTransferWorkflowReadResultV11:
        if not isinstance(query, InferenceTransferWorkflowReadRequestV11):
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
                "exact comparison generation required",
            )
        return cast(
            InferenceTransferWorkflowReadResultV11,
            self._read_comparison(query, selection=selection),
        )

    def _read_comparison(
        self,
        query: InferenceTransferWorkflowReadRequest | InferenceTransferWorkflowReadRequestV11,
        *,
        selection: InferenceTransferPairSubmitRequest | InferenceTransferPairSubmitRequestV11,
    ) -> InferenceTransferWorkflowReadResult | InferenceTransferWorkflowReadResultV11:
        """Read one exact Workflow/mode and bind it to the original selection's pins.

        Pending and pointer-only are preserved. Only the owner-verified canonical
        mode can return comparison content; this adapter does not read NAS or
        interpret metadata JSON as the canonical outer result Artifact member.
        """
        try:
            if isinstance(query, InferenceTransferWorkflowReadRequestV11):
                if not isinstance(selection, InferenceTransferPairSubmitRequestV11):
                    raise ValueError("read generation differs from selection")
                query = parse_workflow_read_request_v11(query.model_dump(mode="json"))
                selection = parse_pair_submit_request_v11(selection.model_dump(mode="json"))
            else:
                if isinstance(selection, InferenceTransferPairSubmitRequestV11):
                    raise ValueError("read generation differs from selection")
                query = parse_workflow_read_request(query.model_dump(mode="json"))
                selection = parse_pair_submit_request(selection.model_dump(mode="json"))
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID", "exact comparison read required"
            ) from None
        principal = self._comparison_principal(PermissionKey.WORKFLOW_READ, selection)
        status, raw = _get(
            _COMPARISON_WORKFLOWS
            + query.workflow_id
            + ("/v1.1" if isinstance(query, InferenceTransferWorkflowReadRequestV11) else "")
            + "?mode="
            + query.mode,
            bearer=self._bearer,
        )
        if status != 200:
            self._comparison_failure(status, raw, "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE")
        try:
            result: InferenceTransferWorkflowReadResult | InferenceTransferWorkflowReadResultV11
            if isinstance(query, InferenceTransferWorkflowReadRequestV11):
                _COMPARISON_READ_VALIDATOR_V11.validate(raw)
                result = parse_workflow_read_result_v11(
                    _COMPARISON_READ_RESPONSE_V11.model_validate(raw).data.model_dump(mode="json")
                )
                validate_workflow_read_result_context_v11(query, result)
            else:
                _COMPARISON_READ_VALIDATOR.validate(raw)
                result = parse_workflow_read_result(
                    _COMPARISON_READ_RESPONSE.model_validate(raw).data.model_dump(mode="json")
                )
                validate_workflow_read_result_context(query, result)
            prepare = selection.snapshot_prepare
            if (
                result.comparison != selection.comparison
                or result.graph_snapshot != prepare.graph_snapshot
                or result.access_policy_revision_id != prepare.access_policy_revision_id
                or result.access_policy_sha256 != prepare.access_policy_sha256
            ):
                raise ValueError("comparison result changed exact selection pins")
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_RESULT_INVALID", "exact comparison reply invalid"
            ) from None
        current = self._comparison_principal(PermissionKey.WORKFLOW_READ, selection)
        if set(current.roles) != set(principal.roles):
            raise ControlPlaneError(
                "CONTROL_AUTHORIZATION_REQUIRED", "current comparison role context changed"
            )
        return result

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        try:
            request = parse_snapshot_request(request.model_dump(mode="json"))
            principal = self.read()
            if actor_id != principal.operator_id or (
                not isinstance(request, InferenceTransferSnapshotPrepareRequest)
                and request.header.actor_id != principal.operator_id
            ):
                raise SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
            status, raw = _post(
                _SNAPSHOT,
                canonical_json_bytes(request.model_dump(mode="json")),
                bearer=self._bearer,
                snapshot_phase=request.phase,
            )
            if status in {401, 403}:
                raise SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
            if status != 200:
                code = raw.get("error_code") if isinstance(raw, dict) else None
                raise SnapshotReadFailure(
                    code if isinstance(code, str) else "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
                )
            _SNAPSHOT_VALIDATOR.validate(raw)
            result = parse_snapshot_result(
                _SNAPSHOT_RESPONSE.model_validate(raw).data.model_dump(mode="json")
            )
            if len(canonical_json_bytes(result.model_dump(mode="json"))) > MAX_SNAPSHOT_FRAME_BYTES:
                raise ValueError("snapshot body exceeds budget")
            if isinstance(request, InferenceTransferSnapshotPrepareRequest) and isinstance(
                result, InferenceTransferSnapshotPrepareResult
            ):
                validate_snapshot_prepare_result(request, result)
                if result.header.actor_id != principal.operator_id:
                    raise ValueError("snapshot actor differs")
            elif isinstance(request, InferenceTransferSnapshotReadRequest) and isinstance(
                result, InferenceTransferSnapshotReadResult
            ):
                validate_snapshot_read_result_context(request, result)
            elif isinstance(request, InferenceTransferSnapshotAuthorizeRequest) and isinstance(
                result, InferenceTransferSnapshotAuthorizeResult
            ):
                validate_snapshot_authorize_result(request, result)
            else:
                raise ValueError("snapshot phase differs")
            return result
        except SnapshotReadFailure:
            raise
        except ControlPlaneError as exc:
            raise SnapshotReadFailure(
                "INFERENCE_TRANSFER_FORBIDDEN"
                if exc.code == "CONTROL_AUTHORIZATION_REQUIRED"
                else "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
            ) from None
        except Exception:
            raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE") from None

    def resolve_metadata(
        self, request: InferenceTransferMetadataResolveRequest
    ) -> InferenceTransferMetadataResolveResult:
        """Resolve only supplied exact pins; never discover latest or infer a Graph pointer."""
        try:
            request = parse_metadata_request(request.model_dump(mode="json"))
            self.read()
            status, raw = _post(
                _METADATA,
                canonical_json_bytes(request.model_dump(mode="json")),
                bearer=self._bearer,
            )
            if status in {401, 403}:
                raise ControlPlaneError("INFERENCE_TRANSFER_FORBIDDEN", "metadata read denied")
            if status != 200:
                code = raw.get("error_code") if isinstance(raw, dict) else None
                raise ControlPlaneError(
                    code
                    if isinstance(code, str) and code in METADATA_ERRORS
                    else "INFERENCE_TRANSFER_METADATA_UNAVAILABLE",
                    "exact metadata read unavailable",
                )
            _METADATA_VALIDATOR.validate(raw)
            result = parse_metadata_result(
                _METADATA_RESPONSE.model_validate(raw).data.model_dump(mode="json")
            )
            validate_metadata_result(request, result)
            return result
        except ControlPlaneError:
            raise
        except Exception:
            raise ControlPlaneError(
                "INFERENCE_TRANSFER_METADATA_UNAVAILABLE", "exact metadata reply invalid"
            ) from None
