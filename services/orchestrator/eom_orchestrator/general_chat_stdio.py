"""Fixed-identity subprocess and bounded JSON-lines transport for native chat.

The caller must run in the dedicated worker service. No operator/slot credential
fallback, inherited environment, shell invocation or network API client exists.
"""

from __future__ import annotations

import grp
import json
import math
import os
import pwd
import selectors
import signal
import stat
import subprocess
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from time import monotonic
from typing import cast

from eom_identifiers import canonical_json_bytes

from eom_orchestrator.general_chat_native import (
    DISABLED_CHAT_FEATURES,
    MAX_EVENT_BYTES,
    RPC_TIMEOUT_SECONDS,
    NativeChatError,
)

CHAT_USER = "eom-cdx-chat"
CHAT_HOME = Path("/srv/eom/worker-homes/eom-cdx-chat")
CHAT_WORKSPACE = Path("/srv/eom/workspaces/general-chat/native")
CHAT_CONFIG = CHAT_HOME / ".codex/config.toml"
CODEX_BINARY = Path("/usr/local/bin/codex")
FIXED_PATH = "/usr/local/bin:/usr/bin:/bin"
EXPECTED_VERSION = "codex-cli 0.160.0"


def native_chat_environment() -> dict[str, str]:
    return {
        "HOME": str(CHAT_HOME),
        "CODEX_HOME": str(CHAT_HOME / ".codex"),
        "PATH": FIXED_PATH,
        "LANG": "C.UTF-8",
        "RUST_LOG": "off",
        "NO_COLOR": "1",
        "TMPDIR": "/tmp",
    }


def native_chat_command(*, model: str) -> list[str]:
    if (
        not model
        or len(model) > 128
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in model
        )
    ):
        raise ValueError("invalid pinned chat model")
    command = [str(CODEX_BINARY)]
    for feature in sorted(DISABLED_CHAT_FEATURES):
        command.extend(["-c", f"features.{feature}=false"])
    for key, value in (
        ("forced_login_method", "chatgpt"),
        ("cli_auth_credentials_store", "file"),
        ("model_provider", "openai"),
        ("model", model),
        ("sandbox_mode", "read-only"),
        ("approval_policy", "never"),
        ("web_search", "disabled"),
        ("log_dir", "/run/eom-general-chat-worker/native-logs"),
    ):
        command.extend(["-c", f"{key}={json.dumps(value)}"])
    for override in (
        "analytics.enabled=false",
        "tools.experimental_request_user_input.enabled=false",
        "tools.update_plan.enabled=false",
    ):
        command.extend(["-c", override])
    command.extend(["app-server", "--strict-config", "--stdio"])
    return command


def require_native_chat_identity() -> None:
    try:
        account = pwd.getpwnam(CHAT_USER)
        if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        groups = {grp.getgrgid(group).gr_name for group in os.getgroups()}
        if groups & {"eom", "sudo", "docker", "lxd", "adm"}:
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        if account.pw_dir != str(CHAT_HOME) or account.pw_shell != "/usr/sbin/nologin":
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        for path in (CHAT_HOME, CHAT_HOME / ".codex"):
            metadata = path.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != account.pw_uid
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        workspace = CHAT_WORKSPACE.lstat()
        config = CHAT_CONFIG.lstat()
        if (
            not stat.S_ISDIR(workspace.st_mode)
            or workspace.st_uid != 0
            or stat.S_IMODE(workspace.st_mode) != 0o750
            or workspace.st_gid != account.pw_gid
            or not stat.S_ISREG(config.st_mode)
            or config.st_uid != 0
            or config.st_gid != account.pw_gid
            or stat.S_IMODE(config.st_mode) != 0o640
        ):
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        if any(CHAT_WORKSPACE.iterdir()):
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        # Empty, root-installed config excludes MCP/plugin providers. CLI overrides
        # pin all policy values; the service must mount this file read-only.
        expected_config = (
            b"# EOM dedicated text-only chat. Configuration is pinned by the launcher.\n"
        )
        if config.st_size != len(expected_config) or CHAT_CONFIG.read_bytes() != expected_config:
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        if not os.statvfs(CHAT_CONFIG).f_flag & os.ST_RDONLY:
            # Root ownership alone cannot prevent rename in a worker-owned home.
            # The service must actually mount its pinned config read-only.
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        link = CODEX_BINARY.lstat()
        binary = CODEX_BINARY.resolve(strict=True).stat()
        if (
            link.st_uid != 0
            or link.st_gid != 0
            or not stat.S_ISREG(binary.st_mode)
            or binary.st_uid != 0
            or binary.st_gid != 0
            or stat.S_IMODE(binary.st_mode) & 0o022
            or not os.access(CODEX_BINARY, os.X_OK)
        ):
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
    except (OSError, KeyError) as exc:
        raise NativeChatError("CHAT_ISOLATION_NOT_READY") from exc


def require_native_chat_capability(*, command: list[str], environment: dict[str, str]) -> None:
    """No inference: validate installed CLI and effective disabled feature inventory."""
    version = subprocess.run(
        [str(CODEX_BINARY), "--version"],
        env=environment,
        cwd=CHAT_WORKSPACE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if version.returncode != 0 or version.stdout.strip() != EXPECTED_VERSION.encode("ascii"):
        raise NativeChatError("CHAT_ISOLATION_NOT_READY")
    # Preserve the same pinned overrides but do not start a native server here.
    if command[-3:] != ["app-server", "--strict-config", "--stdio"]:
        raise NativeChatError("CHAT_ISOLATION_NOT_READY")
    feature_command = [*command[:-3], "features", "list"]
    feature_list = subprocess.run(
        feature_command,
        env=environment,
        cwd=CHAT_WORKSPACE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if feature_list.returncode != 0 or len(feature_list.stdout) > 64000:
        raise NativeChatError("CHAT_ISOLATION_NOT_READY")
    states: dict[str, bool] = {}
    for line in feature_list.stdout.decode("utf-8", errors="strict").splitlines():
        words = line.split()
        if len(words) < 3 or words[-1] not in {"true", "false"} or words[0] in states:
            raise NativeChatError("CHAT_ISOLATION_NOT_READY")
        states[words[0]] = words[-1] == "true"
    if any(states.get(feature) is not False for feature in DISABLED_CHAT_FEATURES):
        raise NativeChatError("CHAT_ISOLATION_NOT_READY")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NativeChatError()
        result[key] = value
    return result


def _no_constant(_: str) -> object:
    raise NativeChatError()


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise NativeChatError()
    return result


class CodexChatStdio:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdin is None or process.stdout is None:
            raise ValueError("native stdio pipes are required")
        self.process = process
        self.reader = selectors.DefaultSelector()
        self.writer = selectors.DefaultSelector()
        self.reader.register(process.stdout, selectors.EVENT_READ)
        self.writer.register(process.stdin, selectors.EVENT_WRITE)
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stdin.fileno(), False)
        self.buffer = bytearray()
        self.closed = False

    @classmethod
    def start(cls, *, model: str) -> CodexChatStdio:
        require_native_chat_identity()
        command = native_chat_command(model=model)
        environment = native_chat_environment()
        require_native_chat_capability(command=command, environment=environment)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            cwd=CHAT_WORKSPACE,
            start_new_session=True,
            bufsize=0,
        )
        return cls(process)

    def send(self, document: Mapping[str, object]) -> None:
        payload = canonical_json_bytes(document) + b"\n"
        if len(payload) > 256000 or self.closed:
            raise NativeChatError()
        deadline = monotonic() + RPC_TIMEOUT_SECONDS
        offset = 0
        while offset < len(payload):
            if monotonic() >= deadline:
                raise TimeoutError()
            for key, _ in self.writer.select(timeout=min(0.25, max(0.0, deadline - monotonic()))):
                try:
                    count = os.write(key.fd, payload[offset:])
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise OSError("native input unavailable")
                offset += count

    def receive(self, *, deadline: float) -> Mapping[str, object]:
        blanks = 0
        while not self.closed:
            if monotonic() >= deadline:
                raise TimeoutError()
            if b"\n" in self.buffer:
                raw, _, remainder = self.buffer.partition(b"\n")
                self.buffer = bytearray(remainder)
                if len(raw) > MAX_EVENT_BYTES:
                    raise NativeChatError()
                if not raw:
                    blanks += 1
                    if blanks > 16:
                        raise NativeChatError()
                    continue
                try:
                    value = json.loads(
                        raw,
                        object_pairs_hook=_unique_object,
                        parse_constant=_no_constant,
                        parse_float=_finite_float,
                    )
                except (UnicodeError, ValueError, RecursionError) as exc:
                    raise NativeChatError() from exc
                if not isinstance(value, dict):
                    raise NativeChatError()
                return cast(dict[str, object], value)
            if len(self.buffer) > MAX_EVENT_BYTES:
                raise NativeChatError()
            for key, _ in self.reader.select(timeout=min(0.25, max(0.0, deadline - monotonic()))):
                try:
                    chunk = os.read(key.fd, 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise OSError("native output unavailable")
                self.buffer.extend(chunk)
        raise OSError("native process closed")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.buffer.clear()
        self.reader.close()
        self.writer.close()
        if self.process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()
