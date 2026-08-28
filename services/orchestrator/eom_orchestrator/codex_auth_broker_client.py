"""Client adapter for the private Codex device-auth broker socket."""

from __future__ import annotations

import grp
import json
import pwd
import socket
import stat
from pathlib import Path
from typing import Any, Literal

from eom_workflow import (
    CodexAuthBrokerRequest,
    CodexAuthBrokerRequestV2,
    CodexAuthBrokerResponse,
    CodexAuthBrokerResponseV2,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from eom_orchestrator.codex_auth_broker_server import (
    BROKER_SOCKET,
    MAX_MESSAGE_BYTES,
    RUNTIME_DIRECTORY_MODE,
    SOCKET_MODE,
)

CONNECT_TIMEOUT_SECONDS = 3.0


class CodexAuthBrokerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Codex auth broker request failed")
        self.code = code


class CodexAuthBrokerClient:
    def __init__(
        self,
        socket_path: Path = BROKER_SOCKET,
        *,
        expected_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.expected_uid = expected_uid
        self.expected_gid = expected_gid

    def request(
        self,
        *,
        action: Literal["STATUS", "REVEAL"],
        enrollment_id: str,
        slot_key: str,
    ) -> CodexAuthBrokerResponse | CodexAuthBrokerResponseV2:
        is_v2 = slot_key == "slot06"
        request_type = CodexAuthBrokerRequestV2 if is_v2 else CodexAuthBrokerRequest
        request = request_type(
            action=action,
            enrollment_id=enrollment_id,
            slot_key=slot_key,
        )
        payload = request.model_dump(mode="json")
        validate_control_contract(
            "codex-auth-broker-request-v2" if is_v2 else "codex-auth-broker-request",
            payload,
        )
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
            connection.sendall(encoded + b"\n")
            raw = self._read_message(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_control_contract(
                "codex-auth-broker-response-v2" if is_v2 else "codex-auth-broker-response",
                value,
            )
            response_type = CodexAuthBrokerResponseV2 if is_v2 else CodexAuthBrokerResponse
            response = response_type.model_validate(value)
        except CodexAuthBrokerError:
            raise
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ) as exc:
            raise CodexAuthBrokerError("CODEX_AUTH_BROKER_RESPONSE_INVALID") from exc
        finally:
            connection.close()
        if response.outcome == "FAILED":
            raise CodexAuthBrokerError(response.error_code or "CODEX_AUTH_BROKER_FAILED")
        return response

    def _validate_socket(self) -> None:
        try:
            expected_uid = (
                pwd.getpwnam("eom-codex-auth-broker").pw_uid
                if self.expected_uid is None
                else self.expected_uid
            )
            expected_gid = (
                grp.getgrnam("eom-codex-auth").gr_gid
                if self.expected_gid is None
                else self.expected_gid
            )
            parent = self.socket_path.parent
            parent_metadata = parent.lstat()
            metadata = self.socket_path.lstat()
        except (KeyError, OSError) as exc:
            raise CodexAuthBrokerError("CODEX_AUTH_BROKER_UNAVAILABLE") from exc
        if (
            parent.is_symlink()
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != expected_uid
            or parent_metadata.st_gid != expected_gid
            or stat.S_IMODE(parent_metadata.st_mode) != RUNTIME_DIRECTORY_MODE
            or self.socket_path.is_symlink()
            or not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or stat.S_IMODE(metadata.st_mode) != SOCKET_MODE
        ):
            raise CodexAuthBrokerError("CODEX_AUTH_BROKER_INVALID")

    @staticmethod
    def _read_message(connection: socket.socket) -> bytes:
        value = bytearray()
        while len(value) <= MAX_MESSAGE_BYTES:
            chunk = connection.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                return bytes(value)
            value.extend(chunk)
        raise ValueError("Codex auth broker response is absent or exceeds its fixed bound")
