from __future__ import annotations

import json
import ssl
import time
from datetime import UTC, datetime, timedelta, timezone
from http.client import HTTPException

import pytest
from eom_orchestrator import codex_distribution_update as distribution
from pydantic import ValidationError

NOW = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)


class _Socket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.read_sizes: list[int] = []
        self.closed = False

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name)

    def read1(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


class _Connection:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.sock = _Socket()
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.requests.append((method, path, headers))

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.closed = True


def _stub_connection(
    monkeypatch: pytest.MonkeyPatch, response: _Response
) -> tuple[_Connection, list[tuple[str, float, ssl.SSLContext]]]:
    connection = _Connection(response)
    calls: list[tuple[str, float, ssl.SSLContext]] = []

    def connect(host: str, *, timeout: float, context: ssl.SSLContext) -> _Connection:
        calls.append((host, timeout, context))
        return connection

    monkeypatch.setattr(distribution, "HTTPSConnection", connect)
    return connection, calls


def _check(
    version: str = "0.160.0", *, timeout: float = 10.0
) -> distribution.CodexDistributionUpdate:
    return distribution.check_codex_distribution_update(
        installed_version=version,
        observed_at=NOW,
        timeout_seconds=timeout,
    )


def _package(version: object = "0.160.0", *, name: object = "@openai/codex") -> bytes:
    return json.dumps({"name": name, "version": version}).encode()


@pytest.mark.parametrize(
    ("installed", "latest", "status"),
    [
        ("0.160.0", "0.160.0", "CURRENT"),
        ("0.9.0", "0.10.0", "UPDATE_AVAILABLE"),
        ("0.160.9", "0.160.10", "UPDATE_AVAILABLE"),
        ("0.999.999", "1.0.0", "UPDATE_AVAILABLE"),
        ("1.0.0", "0.999.999", "INSTALLED_AHEAD"),
        ("0.160.0", "0.159.99", "INSTALLED_AHEAD"),
    ],
)
def test_stable_versions_are_compared_numerically(
    monkeypatch: pytest.MonkeyPatch, installed: str, latest: str, status: str
) -> None:
    response = _Response(_package(latest))
    connection, calls = _stub_connection(monkeypatch, response)

    result = _check(installed)

    assert result.status == status
    assert result.installed_version == installed
    assert result.latest_version == latest
    assert result.error_code is None
    assert result.observed_at == NOW
    assert result.source_uri == distribution.CODEX_DISTRIBUTION_SOURCE_URI
    assert calls[0][0:2] == ("registry.npmjs.org", 10.0)
    assert calls[0][2].verify_mode == ssl.CERT_REQUIRED
    assert calls[0][2].check_hostname
    assert connection.closed and response.closed


@pytest.mark.parametrize(
    "version",
    ["", "v0.160.0", "0.160", "0.0160.0", "0.160.0-alpha", "0.160.0+build", "0.160.0\n"],
)
def test_invalid_installed_version_is_unknown_without_network(
    monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    connection, calls = _stub_connection(monkeypatch, _Response(_package()))

    result = _check(version)

    assert result.status == "UNKNOWN"
    assert result.installed_version is None and result.latest_version is None
    assert result.error_code == "INSTALLED_VERSION_INVALID"
    assert not calls and not connection.requests


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"\xff",
        b"[]",
        b"null",
        _package(name="@untrusted/codex"),
        _package(version=160),
        _package(version="0.160.0-alpha"),
        _package(version="0.160.0+build"),
        _package(version="00.160.0"),
        b'{"name":"@openai/codex","version":"0.160.0","version":"0.161.0"}',
        b'{"name":"@openai/codex","version":"0.160.0","extra":NaN}',
        b'{"dist-tags":{"latest":"0.160.0"}}',
    ],
)
def test_malformed_or_foreign_metadata_is_unknown(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    connection, _ = _stub_connection(monkeypatch, _Response(body))

    result = _check()

    assert result.status == "UNKNOWN" and result.latest_version is None
    assert result.error_code == "METADATA_INVALID"
    assert connection.closed


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_is_rejected_without_another_request(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    response = _Response(
        _package(), status=status, headers={"Location": "https://elsewhere.invalid/private"}
    )
    connection, calls = _stub_connection(monkeypatch, response)

    result = _check()

    assert result.error_code == "METADATA_REDIRECT_REJECTED"
    assert result.status == "UNKNOWN" and result.latest_version is None
    assert len(calls) == len(connection.requests) == 1
    assert not response.read_sizes
    assert "elsewhere" not in result.model_dump_json()


def test_proxy_and_npm_environment_do_not_change_fixed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "npm_config_registry"):
        monkeypatch.setenv(name, "https://proxy.invalid/secret")
    connection, calls = _stub_connection(monkeypatch, _Response(_package()))

    result = _check()

    assert result.status == "CURRENT"
    assert calls[0][0] == "registry.npmjs.org"
    assert connection.requests == [
        (
            "GET",
            "/@openai/codex/latest",
            {
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "eom-codex-distribution-check/1.0",
            },
        )
    ]
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize("status", [204, 401, 404, 429, 500])
def test_non_success_status_is_unknown(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    response = _Response(_package(), status=status)
    _stub_connection(monkeypatch, response)

    assert _check().error_code == "METADATA_HTTP_STATUS"
    assert not response.read_sizes


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Encoding": "gzip"},
        {"Content-Length": "invalid"},
        {"Content-Length": "-1"},
        {"Content-Length": "0"},
        {"Content-Length": "100"},
    ],
)
def test_invalid_headers_or_truncated_length_fail_unknown(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    _stub_connection(monkeypatch, _Response(_package(), headers=headers))

    assert _check().error_code == "METADATA_INVALID"


def test_declared_oversize_is_rejected_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"", headers={"Content-Length": str(distribution.MAX_METADATA_BYTES + 1)})
    _stub_connection(monkeypatch, response)

    assert _check().error_code == "METADATA_TOO_LARGE"
    assert not response.read_sizes


def test_undeclared_oversize_reads_at_most_limit_plus_one(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"x" * (distribution.MAX_METADATA_BYTES + 1000))
    _stub_connection(monkeypatch, response)

    result = _check()

    assert result.error_code == "METADATA_TOO_LARGE"
    assert sum(response.read_sizes) == distribution.MAX_METADATA_BYTES + 1
    assert all(size <= 8192 for size in response.read_sizes)


def test_exact_byte_limit_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = b'{"name":"@openai/codex","version":"0.160.0","extra":"'
    suffix = b'"}'
    body = prefix + b"x" * (distribution.MAX_METADATA_BYTES - len(prefix + suffix)) + suffix
    response = _Response(
        body,
        headers={
            "Content-Length": str(len(body)),
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    _stub_connection(monkeypatch, response)

    assert _check().status == "CURRENT"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("private timeout detail"), "METADATA_TIMEOUT"),
        (OSError("private network detail"), "METADATA_UNAVAILABLE"),
        (HTTPException("private HTTP detail"), "METADATA_UNAVAILABLE"),
    ],
)
def test_network_failure_returns_only_safe_code(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: str
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(distribution, "HTTPSConnection", fail)

    result = _check()

    assert result.status == "UNKNOWN" and result.latest_version is None
    assert result.error_code == code
    assert "private" not in result.model_dump_json()


def test_exhausted_deadline_is_unknown_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, _ = _stub_connection(monkeypatch, _Response(_package()))
    ticks = iter([1.0, 11.1])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))

    result = _check()

    assert result.error_code == "METADATA_TIMEOUT"
    assert connection.closed


@pytest.mark.parametrize("timeout", [0.0, -1.0, 30.1, float("inf"), float("nan"), True])
def test_invalid_timeout_does_not_connect(monkeypatch: pytest.MonkeyPatch, timeout: float) -> None:
    _, calls = _stub_connection(monkeypatch, _Response(_package()))

    with pytest.raises(ValueError, match="timeout"):
        _check(timeout=timeout)

    assert not calls


@pytest.mark.parametrize(
    "now", [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=9)))]
)
def test_observation_requires_utc_without_connecting(
    monkeypatch: pytest.MonkeyPatch, now: datetime
) -> None:
    _, calls = _stub_connection(monkeypatch, _Response(_package()))

    with pytest.raises(ValueError, match="UTC"):
        distribution.check_codex_distribution_update(installed_version="0.160.0", observed_at=now)

    assert not calls


def test_observation_is_frozen_and_rejects_incoherent_known_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_connection(monkeypatch, _Response(_package()))
    result = _check()

    with pytest.raises(ValidationError, match="frozen"):
        result.status = "UNKNOWN"
    with pytest.raises(ValidationError, match="differs"):
        distribution.CodexDistributionUpdate(
            installed_version="0.160.0",
            latest_version="0.161.0",
            status="CURRENT",
            observed_at=NOW,
        )
