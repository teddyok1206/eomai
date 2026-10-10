"""Read-only discovery of the published stable Codex npm distribution.

The fixed HTTPS adapter does not consult npm configuration, proxy environment variables,
or redirects. It never installs a package or invokes Codex's mutating update command.
"""

from __future__ import annotations

import json
import math
import re
import ssl
import time
from datetime import UTC, datetime, timedelta
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODEX_DISTRIBUTION_SOURCE_URI: Literal["https://registry.npmjs.org/@openai/codex/latest"] = (
    "https://registry.npmjs.org/@openai/codex/latest"
)
MAX_METADATA_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 30.0
STABLE_VERSION_PATTERN = r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})"
_STABLE_VERSION = re.compile(STABLE_VERSION_PATTERN, re.ASCII)
_METADATA_HOST = "registry.npmjs.org"
_METADATA_PATH = "/@openai/codex/latest"
_READ_CHUNK_BYTES = 8192

UpdateStatus = Literal["CURRENT", "UPDATE_AVAILABLE", "INSTALLED_AHEAD", "UNKNOWN"]
UpdateErrorCode = Literal[
    "INSTALLED_VERSION_INVALID",
    "METADATA_UNAVAILABLE",
    "METADATA_HTTP_STATUS",
    "METADATA_REDIRECT_REJECTED",
    "METADATA_TOO_LARGE",
    "METADATA_INVALID",
    "METADATA_TIMEOUT",
]


class CodexDistributionUpdate(BaseModel):
    """Small immutable observation, not an installation or capability authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    installed_version: str | None = Field(default=None, pattern=f"^{STABLE_VERSION_PATTERN}$")
    latest_version: str | None = Field(default=None, pattern=f"^{STABLE_VERSION_PATTERN}$")
    status: UpdateStatus
    observed_at: datetime
    source_uri: Literal["https://registry.npmjs.org/@openai/codex/latest"] = (
        CODEX_DISTRIBUTION_SOURCE_URI
    )
    error_code: UpdateErrorCode | None = None

    @model_validator(mode="after")
    def coherent_observation(self) -> CodexDistributionUpdate:
        _require_utc(self.observed_at)
        if any(
            value is not None and _STABLE_VERSION.fullmatch(value) is None
            for value in (self.installed_version, self.latest_version)
        ):
            raise ValueError("distribution version must be exact stable SemVer")
        if self.status == "UNKNOWN":
            if self.latest_version is not None or self.error_code is None:
                raise ValueError("unknown distribution state must not claim a latest version")
            if (self.installed_version is None) != (self.error_code == "INSTALLED_VERSION_INVALID"):
                raise ValueError("unknown installed version requires its explicit error")
        elif (
            self.installed_version is None
            or self.latest_version is None
            or self.error_code is not None
            or self.status != _compare_versions(self.installed_version, self.latest_version)
        ):
            raise ValueError("distribution state differs from its version observations")
        return self


class _MetadataFailure(Exception):
    def __init__(self, code: UpdateErrorCode) -> None:
        self.code = code
        super().__init__(code)


def check_codex_distribution_update(
    *,
    installed_version: str,
    observed_at: datetime,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> CodexDistributionUpdate:
    """Read one fixed public package record; network/malformed observations fail unknown.

    The deadline is checked between bounded reads; every blocking socket operation also
    has a timeout. There is no retry, proxy discovery, redirect, auth, or subprocess.
    """

    _require_utc(observed_at)
    if (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("distribution timeout is outside the bounded interval")
    normalized_time = observed_at.astimezone(UTC)
    if _STABLE_VERSION.fullmatch(installed_version) is None:
        return CodexDistributionUpdate(
            status="UNKNOWN",
            observed_at=normalized_time,
            error_code="INSTALLED_VERSION_INVALID",
        )

    connection: HTTPSConnection | None = None
    try:
        deadline = time.monotonic() + timeout_seconds
        connection = HTTPSConnection(
            _METADATA_HOST,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
        connection.request(
            "GET",
            _METADATA_PATH,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "eom-codex-distribution-check/1.0",
            },
        )
        _set_remaining_timeout(connection, deadline)
        with connection.getresponse() as response:
            raw = _read_metadata(response, connection=connection, deadline=deadline)
        latest_version = _metadata_version(raw)
    except _MetadataFailure as exc:
        error_code = exc.code
    except TimeoutError:
        error_code = "METADATA_TIMEOUT"
    except (OSError, HTTPException):
        error_code = "METADATA_UNAVAILABLE"
    else:
        return CodexDistributionUpdate(
            installed_version=installed_version,
            latest_version=latest_version,
            status=_compare_versions(installed_version, latest_version),
            observed_at=normalized_time,
        )
    finally:
        if connection is not None:
            connection.close()
    return CodexDistributionUpdate(
        installed_version=installed_version,
        status="UNKNOWN",
        observed_at=normalized_time,
        error_code=error_code,
    )


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("distribution observation time must use UTC")


def _compare_versions(installed: str, latest: str) -> UpdateStatus:
    installed_parts = tuple(int(value) for value in installed.split("."))
    latest_parts = tuple(int(value) for value in latest.split("."))
    if installed_parts == latest_parts:
        return "CURRENT"
    return "UPDATE_AVAILABLE" if installed_parts < latest_parts else "INSTALLED_AHEAD"


def _set_remaining_timeout(connection: HTTPSConnection, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _MetadataFailure("METADATA_TIMEOUT")
    if connection.sock is not None:
        connection.sock.settimeout(remaining)


def _read_metadata(
    response: HTTPResponse, *, connection: HTTPSConnection, deadline: float
) -> bytes:
    if 300 <= response.status < 400:
        raise _MetadataFailure("METADATA_REDIRECT_REJECTED")
    if response.status != 200:
        raise _MetadataFailure("METADATA_HTTP_STATUS")
    if (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower() != (
        "application/json"
    ) or (response.getheader("Content-Encoding") or "identity").strip().lower() != "identity":
        raise _MetadataFailure("METADATA_INVALID")
    declared_size = response.getheader("Content-Length")
    if declared_size is not None:
        if not re.fullmatch(r"[0-9]{1,10}", declared_size, re.ASCII):
            raise _MetadataFailure("METADATA_INVALID")
        if int(declared_size) > MAX_METADATA_BYTES:
            raise _MetadataFailure("METADATA_TOO_LARGE")
    chunks: list[bytes] = []
    total = 0
    while True:
        _set_remaining_timeout(connection, deadline)
        chunk = response.read1(min(_READ_CHUNK_BYTES, MAX_METADATA_BYTES + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_METADATA_BYTES:
            raise _MetadataFailure("METADATA_TOO_LARGE")
        chunks.append(chunk)
    _set_remaining_timeout(connection, deadline)
    if declared_size is not None and int(declared_size) != total:
        raise _MetadataFailure("METADATA_INVALID")
    return b"".join(chunks)


def _metadata_version(raw: bytes) -> str:
    try:
        document: object = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_members,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _MetadataFailure("METADATA_INVALID") from exc
    if not isinstance(document, dict) or document.get("name") != "@openai/codex":
        raise _MetadataFailure("METADATA_INVALID")
    version = document.get("version")
    if not isinstance(version, str) or _STABLE_VERSION.fullmatch(version) is None:
        raise _MetadataFailure("METADATA_INVALID")
    return version


def _unique_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate package metadata member")
        document[key] = value
    return document


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-JSON package metadata constant")
