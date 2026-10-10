"""Official guiadmin session and read-only snapshot transport; no refresh or source bypass."""

from __future__ import annotations

import http.client
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from eom_api_contracts.assessment_learning import AssessmentLearningCorpusViewV2
from eom_api_contracts.auth import CurrentOperator, LoginRequest, TokenPair
from eom_api_contracts.common import ListResponse, SingleResponse
from eom_api_contracts.control_plane import ExecutionPresetView
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
_SNAPSHOT = "/api/v1/knowledge/inference-transfer/snapshot"
_METADATA = "/api/v1/knowledge/inference-transfer/metadata"
_ORIGINAL_CORPUS = "/api/v1/assessment-learning-corpus"
_EXECUTION_PRESETS = "/api/v1/execution-presets"
_REQUEST_TARGETS = frozenset(
    {
        ("POST", _LOGIN),
        ("POST", _SNAPSHOT),
        ("POST", _METADATA),
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
) -> tuple[int, object]:
    if (method, path) not in _REQUEST_TARGETS or (method == "GET" and body is not None):
        raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", "fixed request unavailable")
    connection = http.client.HTTPConnection(_HOST, _PORT, timeout=120.0)
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
    path: str, body: bytes | Callable[[], bytes], *, bearer: SecretStr | None = None
) -> tuple[int, object]:
    return _request("POST", path, body, bearer=bearer)


def _get(path: str, *, bearer: SecretStr) -> tuple[int, object]:
    return _request("GET", path, None, bearer=bearer)


class AuthenticatedInferenceTransferHttpSession:
    """Session identity is captured from /me, not a caller-supplied actor string."""

    def __init__(self, bearer: SecretStr, *, refresh: SecretStr | None = None) -> None:
        self._reader = FixedApiControlPrincipalReader(bearer)
        self._bearer, self._refresh = bearer, refresh
        self._operator_id: str | None = None
        self._session_id: str | None = None

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

    def read(self) -> CurrentOperator:
        try:
            value = CurrentOperator.model_validate(self._reader.read().model_dump(mode="json"))
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
            ):
                raise ValueError("actual session changed or unavailable")
            if self._operator_id is None:
                self._operator_id, self._session_id = value.operator_id, value.session_id
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
