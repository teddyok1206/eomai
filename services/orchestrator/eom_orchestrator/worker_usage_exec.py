#!/srv/eom/conda/envs/eom-api/bin/python -I
"""Fixed-slot Codex App Server usage observer with a sanitized /run handoff."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow import CodexUsageObservation, validate_control_contract

CODEX_BINARY = Path("/usr/local/bin/codex")
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SLOT_USERS = {slot: f"eom-cdx-{slot}" for slot in ("01", "02", "03", "04", "05", "06")}
INSTANCE_PATTERN = re.compile(r"^(codexcmd_[0-9a-f]{32})-(authbinding_[0-9a-f]{32})$", re.ASCII)
LIMIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", re.ASCII)
PLAN_TYPES = frozenset(
    {
        "free",
        "go",
        "plus",
        "pro",
        "prolite",
        "team",
        "self_serve_business_prolite",
        "self_serve_business_usage_based",
        "business",
        "ent26",
        "enterprise_cbp_automation",
        "enterprise_cbp_usage_based",
        "enterprise",
        "edu",
        "unknown",
    }
)
MAX_LINE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 512 * 1024
APP_SERVER_TIMEOUT_SECONDS = 45
USAGE_INVALID_EXIT = 40
USAGE_AUTH_REQUIRED_EXIT = 41
USAGE_TIMEOUT_EXIT = 42


def _validate_identity(slot_id: str) -> tuple[Path, Path, Path]:
    account = pwd.getpwnam(SLOT_USERS[slot_id])
    if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
        raise ValueError("usage observer identity differs")
    home = Path("/srv/eom/worker-homes") / account.pw_name
    home_metadata = home.lstat()
    if (
        home.is_symlink()
        or not stat.S_ISDIR(home_metadata.st_mode)
        or home_metadata.st_uid != account.pw_uid
        or home_metadata.st_gid != account.pw_gid
        or stat.S_IMODE(home_metadata.st_mode) != 0o700
    ):
        raise ValueError("worker home boundary differs")
    codex_home = home / ".codex"
    codex_metadata = codex_home.lstat()
    if (
        codex_home.is_symlink()
        or not stat.S_ISDIR(codex_metadata.st_mode)
        or codex_metadata.st_uid != account.pw_uid
        or codex_metadata.st_gid != account.pw_gid
        or stat.S_IMODE(codex_metadata.st_mode) & 0o077
    ):
        raise ValueError("Codex authentication directory boundary differs")
    runtime = Path(f"/run/eom-codex-usage-{slot_id}")
    runtime_metadata = runtime.lstat()
    if (
        runtime.is_symlink()
        or not stat.S_ISDIR(runtime_metadata.st_mode)
        or runtime_metadata.st_uid != account.pw_uid
        or runtime_metadata.st_gid != account.pw_gid
        or stat.S_IMODE(runtime_metadata.st_mode) != 0o770
    ):
        raise ValueError("usage handoff directory boundary differs")
    return home, codex_home, runtime


def _validate_codex_binary() -> None:
    link_metadata = CODEX_BINARY.lstat()
    resolved = CODEX_BINARY.resolve(strict=True)
    metadata = resolved.stat()
    if (
        link_metadata.st_uid != 0
        or link_metadata.st_gid != 0
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise ValueError("Codex executable boundary differs")


def _json_line(document: dict[str, object]) -> bytes:
    return json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def _write_request(process: subprocess.Popen[bytes], document: dict[str, object]) -> None:
    if process.stdin is None:
        raise OSError("Codex App Server input pipe is unavailable")
    process.stdin.write(_json_line(document))
    process.stdin.flush()


def _read_responses(
    process: subprocess.Popen[bytes], expected_ids: frozenset[int]
) -> dict[int, Any]:
    if process.stdout is None:
        raise OSError("Codex App Server output pipe is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    started = monotonic()
    pending = set(expected_ids)
    responses: dict[int, Any] = {}
    buffered = bytearray()
    total = 0
    try:
        while pending:
            if monotonic() - started > APP_SERVER_TIMEOUT_SECONDS:
                raise TimeoutError("Codex App Server response timed out")
            if process.poll() is not None and not buffered:
                raise ValueError("Codex App Server stopped before completing usage observation")
            for key, _ in selector.select(timeout=0.25):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("Codex App Server response is too large")
                buffered.extend(chunk)
                while b"\n" in buffered:
                    raw, _, remainder = buffered.partition(b"\n")
                    buffered = bytearray(remainder)
                    if not raw:
                        continue
                    if len(raw) > MAX_LINE_BYTES:
                        raise ValueError("Codex App Server response line is too large")
                    value = json.loads(raw)
                    if not isinstance(value, dict):
                        raise ValueError("Codex App Server response is not an object")
                    response_id = value.get("id")
                    if response_id not in pending:
                        continue
                    if "error" in value or "result" not in value:
                        raise ValueError("Codex App Server returned an error")
                    responses[response_id] = value["result"]
                    pending.remove(response_id)
    finally:
        selector.close()
    return responses


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def _utc_from_unix(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("rate-limit reset timestamp is invalid")
    parsed = datetime.fromtimestamp(value, tz=UTC)
    if not datetime(2020, 1, 1, tzinfo=UTC) <= parsed <= datetime(2100, 1, 1, tzinfo=UTC):
        raise ValueError("rate-limit reset timestamp is outside the reviewed range")
    return parsed


def _safe_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value != value.strip():
        raise ValueError("rate-limit display name is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("rate-limit display name contains controls")
    return value


def _normalized_windows(result: object) -> tuple[dict[str, object], ...]:
    if not isinstance(result, dict):
        raise ValueError("rate-limit response is not an object")
    raw_buckets = result.get("rateLimitsByLimitId")
    if isinstance(raw_buckets, dict) and raw_buckets:
        buckets = tuple(raw_buckets.items())
    else:
        buckets = (("codex", result.get("rateLimits")),)
    windows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for fallback_id, snapshot in buckets:
        if not isinstance(fallback_id, str) or not isinstance(snapshot, dict):
            raise ValueError("rate-limit bucket is invalid")
        raw_limit_id = snapshot.get("limitId")
        limit_id = raw_limit_id if isinstance(raw_limit_id, str) and raw_limit_id else fallback_id
        if LIMIT_ID_PATTERN.fullmatch(limit_id) is None:
            raise ValueError("rate-limit identity is invalid")
        limit_name = _safe_name(snapshot.get("limitName"))
        for key, kind in (("primary", "PRIMARY"), ("secondary", "SECONDARY")):
            raw_window = snapshot.get(key)
            if raw_window is None:
                continue
            if not isinstance(raw_window, dict):
                raise ValueError("rate-limit window is invalid")
            used_percent = raw_window.get("usedPercent")
            duration = raw_window.get("windowDurationMins")
            if (
                not isinstance(used_percent, int)
                or isinstance(used_percent, bool)
                or not 0 <= used_percent <= 100
                or (
                    duration is not None
                    and (
                        not isinstance(duration, int)
                        or isinstance(duration, bool)
                        or not 1 <= duration <= 525_600
                    )
                )
            ):
                raise ValueError("rate-limit window values are invalid")
            identity = (limit_id, kind)
            if identity in seen:
                raise ValueError("rate-limit windows are duplicated")
            seen.add(identity)
            windows.append(
                {
                    "limit_id": limit_id,
                    "limit_name": limit_name,
                    "window_kind": kind,
                    "used_percent": used_percent,
                    "window_duration_minutes": duration,
                    "resets_at": _utc_from_unix(raw_window.get("resetsAt")),
                }
            )
    if not windows:
        raise ValueError("rate-limit response contains no usage windows")
    windows.sort(key=lambda value: (str(value["limit_id"]), str(value["window_kind"])))
    return tuple(windows)


def _observation_document(
    *, command_id: str, binding_id: str, slot_id: str, account_result: object, usage_result: object
) -> dict[str, object]:
    if not isinstance(account_result, dict):
        raise ValueError("Codex account response is not an object")
    account = account_result.get("account")
    if not isinstance(account, dict) or account.get("type") != "chatgpt":
        raise PermissionError("Codex slot does not use ChatGPT authentication")
    plan_type = account.get("planType")
    if not isinstance(plan_type, str) or plan_type not in PLAN_TYPES:
        raise ValueError("Codex account plan is invalid")
    document: dict[str, object] = {
        "schema_version": "codex-usage-observation/1.0",
        "command_id": command_id,
        "binding_id": binding_id,
        "slot_key": f"slot{slot_id}",
        "account_type": "chatgpt",
        "plan_type": plan_type,
        "windows": _normalized_windows(usage_result),
        "observed_at": datetime.now(UTC),
        "observation_sha256": "sha256:" + "0" * 64,
    }
    normalized = CodexUsageObservation.model_validate(document).model_dump(mode="json")
    normalized["observation_sha256"] = content_sha256(
        {key: value for key, value in normalized.items() if key != "observation_sha256"}
    )
    validate_control_contract("codex-usage-observation", normalized)
    return normalized


def _write_exclusive(path: Path, document: dict[str, object]) -> None:
    payload = canonical_json_bytes(document)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o640,
    )
    try:
        os.fchmod(descriptor, 0o640)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute(slot_id: str, command_id: str, binding_id: str) -> int:
    home, codex_home, runtime = _validate_identity(slot_id)
    _validate_codex_binary()
    handoff = runtime / f"{command_id}.json"
    if handoff.exists() or handoff.is_symlink():
        raise FileExistsError("usage handoff already exists")
    log_directory = Path(tempfile.mkdtemp(prefix="eom-codex-usage-"))
    environment = {
        "CODEX_HOME": str(codex_home),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PATH": PATH_VALUE,
        "RUST_LOG": "off",
        "NO_COLOR": "1",
    }
    escaped_log_directory = str(log_directory).replace("\\", "\\\\").replace('"', '\\"')
    process = subprocess.Popen(
        (
            str(CODEX_BINARY),
            "-c",
            'forced_login_method="chatgpt"',
            "-c",
            'cli_auth_credentials_store="file"',
            "-c",
            f'log_dir="{escaped_log_directory}"',
            "app-server",
            "--stdio",
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    try:
        _write_request(
            process,
            {
                "id": 0,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "eom-codex-usage", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": False},
                },
            },
        )
        _read_responses(process, frozenset({0}))
        _write_request(process, {"method": "initialized"})
        _write_request(
            process,
            {"id": 1, "method": "account/read", "params": {"refreshToken": False}},
        )
        _write_request(process, {"id": 2, "method": "account/rateLimits/read"})
        responses = _read_responses(process, frozenset({1, 2}))
        document = _observation_document(
            command_id=command_id,
            binding_id=binding_id,
            slot_id=slot_id,
            account_result=responses[1],
            usage_result=responses[2],
        )
        _write_exclusive(handoff, document)
    finally:
        _terminate(process)
        shutil.rmtree(log_directory)
    print("CODEX_USAGE_READY", file=sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-worker-codex-usage")
    parser.add_argument("--slot", choices=tuple(SLOT_USERS), required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args(argv)
    match = INSTANCE_PATTERN.fullmatch(args.instance)
    if match is None:
        print("CODEX_USAGE_INVALID", file=sys.stdout)
        return USAGE_INVALID_EXIT
    try:
        return execute(args.slot, match.group(1), match.group(2))
    except TimeoutError:
        print("CODEX_USAGE_TIMEOUT", file=sys.stdout)
        return USAGE_TIMEOUT_EXIT
    except PermissionError:
        print("CODEX_USAGE_AUTH_REQUIRED", file=sys.stdout)
        return USAGE_AUTH_REQUIRED_EXIT
    except (FileExistsError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        print("CODEX_USAGE_INVALID", file=sys.stdout)
        return USAGE_INVALID_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
