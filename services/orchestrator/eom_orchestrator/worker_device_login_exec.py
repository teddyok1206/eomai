#!/srv/eom/conda/envs/eom-api/bin/python -I
"""Root-installed fixed-identity Codex device-login helper.

The helper runs as one eom-cdx-0N identity. It never prints or persists raw
Codex output and materializes only schema-valid short-lived /run handoff data.
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

from eom_identifiers import canonical_json_bytes
from eom_workflow import CodexDeviceChallenge, CodexDeviceLoginStatus, validate_control_contract

CODEX_BINARY = Path("/usr/local/bin/codex")
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SLOT_USERS = {slot: f"eom-cdx-{slot}" for slot in ("01", "02", "03", "04", "05")}
ENROLLMENT_PATTERN = re.compile(r"^authflow_[0-9a-f]{32}$", re.ASCII)
URL_PATTERN = re.compile(rb"https://auth\.openai\.com(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*)?")
CODE_PATTERN = re.compile(rb"(?<![A-Z0-9])([A-Z0-9]{3,12}-[A-Z0-9]{3,12})(?![A-Z0-9])")
MAX_OUTPUT_BYTES = 64 * 1024
LOGIN_TIMEOUT_SECONDS = 10 * 60
CHALLENGE_TTL = timedelta(minutes=10)
DEVICE_LOGIN_FAILED_EXIT = 30
DEVICE_LOGIN_INVALID_EXIT = 31
DEVICE_LOGIN_TIMEOUT_EXIT = 32


def _now() -> datetime:
    return datetime.now(UTC)


def _validate_identity(slot_id: str) -> tuple[Path, Path, Path]:
    linux_user = SLOT_USERS[slot_id]
    account = pwd.getpwnam(linux_user)
    if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
        raise ValueError("device-login identity differs")
    home = Path("/srv/eom/worker-homes") / linux_user
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
    try:
        codex_metadata = codex_home.lstat()
    except FileNotFoundError:
        codex_home.mkdir(mode=0o700)
        codex_metadata = codex_home.lstat()
    if (
        codex_home.is_symlink()
        or not stat.S_ISDIR(codex_metadata.st_mode)
        or codex_metadata.st_uid != account.pw_uid
        or codex_metadata.st_gid != account.pw_gid
        or stat.S_IMODE(codex_metadata.st_mode) & 0o077
    ):
        raise ValueError("Codex authentication directory boundary differs")
    runtime = Path(f"/run/eom-codex-login-{slot_id}")
    runtime_metadata = runtime.lstat()
    if (
        runtime.is_symlink()
        or not stat.S_ISDIR(runtime_metadata.st_mode)
        or runtime_metadata.st_uid != account.pw_uid
        or runtime_metadata.st_gid != account.pw_gid
        or stat.S_IMODE(runtime_metadata.st_mode) != 0o750
    ):
        raise ValueError("device-login runtime boundary differs")
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


def _write_exclusive(path: Path, document: dict[str, object]) -> None:
    payload = canonical_json_bytes(document)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o640,
    )
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _replace_status(path: Path, document: dict[str, object]) -> None:
    normalized = CodexDeviceLoginStatus.model_validate(document).model_dump(mode="json")
    validate_control_contract("codex-device-login-status", normalized)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _write_exclusive(temporary, normalized)
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _write_challenge(path: Path, document: dict[str, object]) -> None:
    normalized = CodexDeviceChallenge.model_validate(document).model_dump(mode="json")
    validate_control_contract("codex-device-challenge", normalized)
    _write_exclusive(path, normalized)


def _status_document(
    *, enrollment_id: str, slot_id: str, state: str, reason_code: str | None
) -> dict[str, object]:
    return {
        "schema_version": "codex-device-login-status/1.0",
        "enrollment_id": enrollment_id,
        "slot_key": f"slot{slot_id}",
        "state": state,
        "reason_code": reason_code,
        "updated_at": _now(),
    }


def _safe_remove(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise ValueError("device-login handoff is unsafe")
    path.unlink()


def _remove_log_directory(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("device-login log directory is unsafe")
    shutil.rmtree(path)
    if path.exists() or path.is_symlink():
        raise OSError("device-login log cleanup failed")


def _environment(home: Path, codex_home: Path, log_directory: Path) -> dict[str, str]:
    return {
        "CODEX_HOME": str(codex_home),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PATH": PATH_VALUE,
        "RUST_LOG": "off",
        "NO_COLOR": "1",
    }


def _config_arguments(log_directory: Path) -> tuple[str, ...]:
    escaped = str(log_directory).replace("\\", "\\\\").replace('"', '\\"')
    return (
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'cli_auth_credentials_store="file"',
        "-c",
        f'log_dir="{escaped}"',
    )


def _collect_device_login(
    *,
    environment: dict[str, str],
    log_directory: Path,
    enrollment_id: str,
    slot_id: str,
    status_path: Path,
    challenge_path: Path,
) -> int:
    arguments = (
        str(CODEX_BINARY),
        "login",
        "--device-auth",
        *_config_arguments(log_directory),
    )
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        start_new_session=True,
    )
    if process.stdout is None:
        raise OSError("Codex device-login output pipe is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    started = monotonic()
    collected = bytearray()
    challenge_written = False
    try:
        while process.poll() is None:
            if monotonic() - started > LOGIN_TIMEOUT_SECONDS:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                return DEVICE_LOGIN_TIMEOUT_EXIT
            for key, _ in selector.select(timeout=0.25):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    continue
                collected.extend(chunk)
                if len(collected) > MAX_OUTPUT_BYTES:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    return DEVICE_LOGIN_INVALID_EXIT
                if not challenge_written:
                    url_match = URL_PATTERN.search(collected)
                    code_match = CODE_PATTERN.search(collected)
                    if url_match is not None and code_match is not None:
                        issued_at = _now()
                        _write_challenge(
                            challenge_path,
                            {
                                "schema_version": "codex-device-challenge/1.0",
                                "enrollment_id": enrollment_id,
                                "slot_key": f"slot{slot_id}",
                                "verification_uri": url_match.group(0).decode("ascii"),
                                "user_code": code_match.group(1).decode("ascii"),
                                "issued_at": issued_at,
                                "expires_at": issued_at + CHALLENGE_TTL,
                            },
                        )
                        _replace_status(
                            status_path,
                            _status_document(
                                enrollment_id=enrollment_id,
                                slot_id=slot_id,
                                state="WAITING_FOR_USER",
                                reason_code=None,
                            ),
                        )
                        challenge_written = True
                        collected.clear()
        process.wait(timeout=5)
    finally:
        selector.close()
        process.stdout.close()
    if process.returncode != 0 or not challenge_written:
        return DEVICE_LOGIN_FAILED_EXIT if challenge_written else DEVICE_LOGIN_INVALID_EXIT
    status = subprocess.run(
        (str(CODEX_BINARY), "login", "status", *_config_arguments(log_directory)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        env=environment,
        timeout=30,
    )
    return 0 if status.returncode == 0 else DEVICE_LOGIN_FAILED_EXIT


def execute(slot_id: str, enrollment_id: str) -> int:
    if ENROLLMENT_PATTERN.fullmatch(enrollment_id) is None:
        raise ValueError("device-login enrollment identity is invalid")
    home, codex_home, runtime = _validate_identity(slot_id)
    _validate_codex_binary()
    status_path = runtime / f"{enrollment_id}.status.json"
    challenge_path = runtime / f"{enrollment_id}.challenge.json"
    log_directory = runtime / f"{enrollment_id}.logs"
    if status_path.exists() or challenge_path.exists() or log_directory.exists():
        raise FileExistsError("device-login enrollment handoff already exists")
    log_directory.mkdir(mode=0o700)
    _replace_status(
        status_path,
        _status_document(
            enrollment_id=enrollment_id,
            slot_id=slot_id,
            state="STARTING",
            reason_code=None,
        ),
    )
    environment = _environment(home, codex_home, log_directory)
    result = DEVICE_LOGIN_INVALID_EXIT
    cleanup_failed = False
    try:
        result = _collect_device_login(
            environment=environment,
            log_directory=log_directory,
            enrollment_id=enrollment_id,
            slot_id=slot_id,
            status_path=status_path,
            challenge_path=challenge_path,
        )
    except subprocess.TimeoutExpired:
        result = DEVICE_LOGIN_TIMEOUT_EXIT
    finally:
        try:
            _remove_log_directory(log_directory)
        except (OSError, ValueError):
            cleanup_failed = True
    _safe_remove(challenge_path)
    if cleanup_failed:
        state, reason_code = "FAILED", "CODEX_DEVICE_LOGIN_LOG_CLEANUP_FAILED"
        result = DEVICE_LOGIN_INVALID_EXIT
    elif result == 0:
        state, reason_code = "SUCCEEDED", None
    elif result == DEVICE_LOGIN_TIMEOUT_EXIT:
        state, reason_code = "EXPIRED", "CODEX_DEVICE_LOGIN_EXPIRED"
    elif result == DEVICE_LOGIN_FAILED_EXIT:
        state, reason_code = "FAILED", "CODEX_DEVICE_LOGIN_FAILED"
    else:
        state, reason_code = "FAILED", "CODEX_DEVICE_LOGIN_OUTPUT_INVALID"
    _replace_status(
        status_path,
        _status_document(
            enrollment_id=enrollment_id,
            slot_id=slot_id,
            state=state,
            reason_code=reason_code,
        ),
    )
    print(f"CODEX_DEVICE_LOGIN_{state}", file=sys.stdout)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-worker-device-login")
    parser.add_argument("--slot", choices=tuple(SLOT_USERS), required=True)
    parser.add_argument("--enrollment-id", required=True)
    args = parser.parse_args(argv)
    try:
        return execute(args.slot, args.enrollment_id)
    except (KeyError, OSError, ValueError):
        print("CODEX_DEVICE_LOGIN_INVALID", file=sys.stdout)
        return DEVICE_LOGIN_INVALID_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
