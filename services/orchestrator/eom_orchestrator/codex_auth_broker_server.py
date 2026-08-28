"""Private Unix-socket broker for one-time Codex device challenges."""

from __future__ import annotations

import grp
import json
import os
import pwd
import socket
import socketserver
import stat
import struct
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast

from eom_workflow import (
    CodexAuthBrokerRequest,
    CodexAuthBrokerRequestV2,
    CodexAuthBrokerResponse,
    CodexAuthBrokerResponseV2,
    CodexDeviceChallenge,
    CodexDeviceChallengeV2,
    CodexDeviceLoginStatus,
    CodexDeviceLoginStatusV2,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

BROKER_SOCKET = Path("/run/eom-codex-auth-broker/broker.sock")
MAX_MESSAGE_BYTES = 4096
SOCKET_MODE = 0o660
RUNTIME_DIRECTORY_MODE = 0o750
HANDOFF_MODE = 0o640
SLOT_IDS = ("01", "02", "03", "04", "05", "06")


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = True


class _BrokerHandler(socketserver.StreamRequestHandler):
    server: CodexAuthBrokerServer

    def handle(self) -> None:
        peer_uid = self.server.peer_uid(self.request)
        if peer_uid is None:
            return
        raw = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
        if not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE_BYTES:
            self.server.write_error(self.wfile, "CODEX_AUTH_BROKER_REQUEST_INVALID")
            return
        try:
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            is_v2 = value.get("schema_version") == "codex-auth-broker-request/1.1"
            request_type = CodexAuthBrokerRequestV2 if is_v2 else CodexAuthBrokerRequest
            validate_control_contract(
                "codex-auth-broker-request-v2" if is_v2 else "codex-auth-broker-request",
                value,
            )
            request = request_type.model_validate(value)
            response = self.server.execute(request, caller_uid=peer_uid)
        except (
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ):
            self.server.write_error(self.wfile, "CODEX_AUTH_BROKER_REQUEST_INVALID")
            return
        self.server.write_response(self.wfile, response)


class CodexAuthBrokerServer(_ThreadingUnixServer):
    """Read-only handoff broker; only the fixed Application API UID may connect."""

    def __init__(
        self,
        *,
        socket_path: Path = BROKER_SOCKET,
        allowed_uids: frozenset[int] | None = None,
        reveal_uids: frozenset[int] | None = None,
        expected_gid: int | None = None,
        handoff_root: Path = Path("/run"),
        slot_identities: dict[str, tuple[int, int]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.socket_path = socket_path
        if allowed_uids is None:
            api_uid = pwd.getpwnam("eom-api").pw_uid
            self.allowed_uids = frozenset({api_uid, pwd.getpwnam("eom-workflow-runner").pw_uid})
            self.reveal_uids = frozenset({api_uid}) if reveal_uids is None else reveal_uids
        else:
            self.allowed_uids = allowed_uids
            self.reveal_uids = allowed_uids if reveal_uids is None else reveal_uids
        if not self.reveal_uids or not self.reveal_uids.issubset(self.allowed_uids):
            raise ValueError("Codex auth broker reveal identities are invalid")
        self.expected_gid = (
            grp.getgrnam("eom-codex-auth").gr_gid if expected_gid is None else expected_gid
        )
        self.handoff_root = handoff_root
        self.slot_identities = slot_identities or {
            slot: (
                pwd.getpwnam(f"eom-cdx-{slot}").pw_uid,
                pwd.getpwnam(f"eom-cdx-{slot}").pw_gid,
            )
            for slot in SLOT_IDS
        }
        self.now = now or (lambda: datetime.now(UTC))
        self._revealed: set[str] = set()
        self._reveal_lock = Lock()
        self._validate_runtime_directory()
        if socket_path.exists() or socket_path.is_symlink():
            raise RuntimeError("Codex auth broker socket path is not fresh")
        super().__init__(str(socket_path), _BrokerHandler)
        socket_path.chmod(SOCKET_MODE)
        metadata = socket_path.lstat()
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != SOCKET_MODE
        ):
            self.server_close()
            raise RuntimeError("Codex auth broker socket metadata mismatch")

    def _validate_runtime_directory(self) -> None:
        parent = self.socket_path.parent
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or parent.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != RUNTIME_DIRECTORY_MODE
        ):
            raise RuntimeError("Codex auth broker runtime directory contract mismatch")

    def peer_uid(self, connection: socket.socket) -> int | None:
        try:
            raw = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            if not isinstance(raw, bytes):
                return None
            _pid, uid, _gid = cast(tuple[int, int, int], struct.unpack("3i", raw))
        except (OSError, struct.error):
            return None
        return uid if uid in self.allowed_uids else None

    def execute(
        self,
        request: CodexAuthBrokerRequest | CodexAuthBrokerRequestV2,
        *,
        caller_uid: int | None = None,
    ) -> CodexAuthBrokerResponse | CodexAuthBrokerResponseV2:
        is_v2 = request.schema_version == "codex-auth-broker-request/1.1"
        effective_caller = os.geteuid() if caller_uid is None else caller_uid
        if effective_caller not in self.allowed_uids:
            return self.error_response("CODEX_AUTH_BROKER_CALLER_DENIED", is_v2=is_v2)
        if request.action == "REVEAL" and effective_caller not in self.reveal_uids:
            return self.error_response("CODEX_AUTH_BROKER_REVEAL_DENIED", is_v2=is_v2)
        slot_id = request.slot_key.removeprefix("slot")
        if slot_id not in SLOT_IDS:
            return self.error_response("CODEX_AUTH_BROKER_SLOT_INVALID", is_v2=is_v2)
        status_path = self._handoff_path(slot_id, request.enrollment_id, "status")
        try:
            status_type = CodexDeviceLoginStatusV2 if is_v2 else CodexDeviceLoginStatus
            status = status_type.model_validate(
                self._read_document(
                    status_path,
                    "codex-device-login-status-v2" if is_v2 else "codex-device-login-status",
                    slot_id,
                )
            )
        except FileNotFoundError:
            return self.error_response("CODEX_AUTH_CHALLENGE_NOT_READY", is_v2=is_v2)
        except (OSError, ValueError, JsonSchemaValidationError, ValidationError):
            return self.error_response("CODEX_AUTH_HANDOFF_INVALID", is_v2=is_v2)
        if status.enrollment_id != request.enrollment_id or status.slot_key != request.slot_key:
            return self.error_response("CODEX_AUTH_HANDOFF_IDENTITY_MISMATCH", is_v2=is_v2)
        challenge = None
        if request.action == "REVEAL":
            if status.state != "WAITING_FOR_USER":
                return self.error_response("CODEX_AUTH_CHALLENGE_NOT_AVAILABLE", is_v2=is_v2)
            challenge_path = self._handoff_path(slot_id, request.enrollment_id, "challenge")
            try:
                with self._reveal_lock:
                    if request.enrollment_id in self._revealed:
                        return self.error_response(
                            "CODEX_AUTH_CHALLENGE_ALREADY_REVEALED", is_v2=is_v2
                        )
                    challenge_type = CodexDeviceChallengeV2 if is_v2 else CodexDeviceChallenge
                    challenge = challenge_type.model_validate(
                        self._read_document(
                            challenge_path,
                            "codex-device-challenge-v2" if is_v2 else "codex-device-challenge",
                            slot_id,
                        )
                    )
                    if (
                        challenge.enrollment_id != request.enrollment_id
                        or challenge.slot_key != request.slot_key
                    ):
                        raise ValueError("device challenge identity mismatch")
                    if challenge.expires_at <= self.now():
                        return self.error_response("CODEX_AUTH_CHALLENGE_EXPIRED", is_v2=is_v2)
                    self._revealed.add(request.enrollment_id)
            except FileNotFoundError:
                return self.error_response("CODEX_AUTH_CHALLENGE_ALREADY_REVEALED", is_v2=is_v2)
            except (OSError, ValueError, JsonSchemaValidationError, ValidationError):
                return self.error_response("CODEX_AUTH_HANDOFF_INVALID", is_v2=is_v2)
        response_type = CodexAuthBrokerResponseV2 if is_v2 else CodexAuthBrokerResponse
        return response_type(
            outcome="OK",
            status=status,  # type: ignore[arg-type]
            challenge=challenge,  # type: ignore[arg-type]
            error_code=None,
        )

    def _handoff_path(self, slot_id: str, enrollment_id: str, kind: str) -> Path:
        return self.handoff_root / f"eom-codex-login-{slot_id}" / f"{enrollment_id}.{kind}.json"

    def _read_document(self, path: Path, schema_name: str, slot_id: str) -> dict[str, Any]:
        parent = path.parent
        owner_uid, owner_gid = self.slot_identities[slot_id]
        parent_metadata = parent.lstat()
        if (
            parent.is_symlink()
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != owner_uid
            or parent_metadata.st_gid != owner_gid
            or stat.S_IMODE(parent_metadata.st_mode) != 0o750
        ):
            raise ValueError("device-login runtime directory is invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != owner_uid
                or metadata.st_gid != owner_gid
                or stat.S_IMODE(metadata.st_mode) != HANDOFF_MODE
                or metadata.st_size <= 0
                or metadata.st_size > MAX_MESSAGE_BYTES
            ):
                raise ValueError("device-login handoff metadata is invalid")
            raw = os.read(descriptor, MAX_MESSAGE_BYTES + 1)
        finally:
            os.close(descriptor)
        value: Any = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("device-login handoff is not an object")
        validate_control_contract(schema_name, value)
        return value

    def handle_error(self, _request: object, _client_address: object) -> None:
        return

    @staticmethod
    def error_response(
        error_code: str, *, is_v2: bool = False
    ) -> CodexAuthBrokerResponse | CodexAuthBrokerResponseV2:
        response_type = CodexAuthBrokerResponseV2 if is_v2 else CodexAuthBrokerResponse
        return response_type(
            outcome="FAILED",
            status=None,
            challenge=None,
            error_code=error_code,
        )

    @staticmethod
    def write_response(
        stream: Any, value: CodexAuthBrokerResponse | CodexAuthBrokerResponseV2
    ) -> None:
        payload = value.model_dump(mode="json")
        validate_control_contract(
            "codex-auth-broker-response-v2"
            if value.schema_version == "codex-auth-broker-response/1.1"
            else "codex-auth-broker-response",
            payload,
        )
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(encoded) + 1 > MAX_MESSAGE_BYTES:
            raise RuntimeError("Codex auth broker response exceeded its fixed bound")
        stream.write(encoded + b"\n")

    @classmethod
    def write_error(cls, stream: Any, error_code: str) -> None:
        cls.write_response(stream, cls.error_response(error_code))

    def server_close(self) -> None:
        super().server_close()
        try:
            metadata = self.socket_path.lstat()
        except OSError:
            return
        if (
            stat.S_ISSOCK(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and metadata.st_gid == self.expected_gid
        ):
            self.socket_path.unlink()


def main() -> int:
    server = CodexAuthBrokerServer()
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
