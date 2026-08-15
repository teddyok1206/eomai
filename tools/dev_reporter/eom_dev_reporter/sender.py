"""Best-effort Incoming Webhook delivery and redacted local archive."""

from __future__ import annotations

import json
import os
import pwd
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from eom_dev_reporter.models import DevelopmentProgressReport, validate_report
from eom_dev_reporter.redaction import redact_value

DEFAULT_SECRET_PATH = Path("/etc/eom/secrets/dev-slack.env")
DEFAULT_ARCHIVE_ROOT = Path("/srv/eom/state/dev-reports")
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_DELIVERY_ATTEMPTS = 3


class ReporterErrorCode(StrEnum):
    DEV_REPORT_SCHEMA_INVALID = "DEV_REPORT_SCHEMA_INVALID"
    DEV_REPORT_NOT_CONFIGURED = "DEV_REPORT_NOT_CONFIGURED"
    DEV_REPORT_DISABLED = "DEV_REPORT_DISABLED"
    DEV_REPORT_DNS_ERROR = "DEV_REPORT_DNS_ERROR"
    DEV_REPORT_NETWORK_TIMEOUT = "DEV_REPORT_NETWORK_TIMEOUT"
    DEV_REPORT_HTTP_ERROR = "DEV_REPORT_HTTP_ERROR"
    DEV_REPORT_INVALID_RESPONSE = "DEV_REPORT_INVALID_RESPONSE"
    DEV_REPORT_INVALID_PAYLOAD = "DEV_REPORT_INVALID_PAYLOAD"
    DEV_REPORT_ARCHIVE_FAILED = "DEV_REPORT_ARCHIVE_FAILED"


class DeliveryStatus(StrEnum):
    SENT = "SENT"
    DRY_RUN = "DRY_RUN"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DISABLED = "DISABLED"
    DNS_ERROR = "DNS_ERROR"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"


@dataclass(frozen=True)
class ReporterConfig:
    enabled: bool
    webhook_url: str | None


@dataclass(frozen=True)
class DeliveryResult:
    status: DeliveryStatus
    attempts: int
    http_status: int | None = None
    error_code: ReporterErrorCode | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in {DeliveryStatus.SENT, DeliveryStatus.DRY_RUN}


@dataclass(frozen=True)
class ArchiveResult:
    path: Path | None
    error_code: ReporterErrorCode | None = None


Post = Callable[[str, bytes, float], tuple[int, bytes]]


def load_reporter_config(secret_path: Path = DEFAULT_SECRET_PATH) -> ReporterConfig:
    values: dict[str, str] = {}
    if secret_path.is_file():
        values.update(_parse_environment_file(secret_path))
    for key in ("EOM_DEV_SLACK_REPORTING_ENABLED", "EOM_DEV_SLACK_WEBHOOK_URL"):
        if key in os.environ:
            values[key] = os.environ[key]
    enabled = values.get("EOM_DEV_SLACK_REPORTING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    webhook = values.get("EOM_DEV_SLACK_WEBHOOK_URL") or None
    return ReporterConfig(enabled=enabled, webhook_url=webhook)


def valid_webhook_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "hooks.slack.com"
        and parsed.port in {None, 443}
        and parsed.path.startswith("/services/")
        and len(parsed.path.split("/")) >= 5
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def send_webhook(
    payload: Mapping[str, Any],
    config: ReporterConfig,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    post: Post | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> DeliveryResult:
    if not _valid_payload(payload):
        return DeliveryResult(
            DeliveryStatus.INVALID_PAYLOAD,
            0,
            error_code=ReporterErrorCode.DEV_REPORT_INVALID_PAYLOAD,
        )
    webhook_url = config.webhook_url
    if not valid_webhook_url(webhook_url) or webhook_url is None:
        return DeliveryResult(
            DeliveryStatus.NOT_CONFIGURED,
            0,
            error_code=ReporterErrorCode.DEV_REPORT_NOT_CONFIGURED,
        )
    if not config.enabled:
        return DeliveryResult(
            DeliveryStatus.DISABLED,
            0,
            error_code=ReporterErrorCode.DEV_REPORT_DISABLED,
        )

    body = json.dumps(redact_value(dict(payload)), ensure_ascii=False).encode("utf-8")
    transport = post or _post
    last = DeliveryResult(
        DeliveryStatus.INVALID_RESPONSE,
        0,
        error_code=ReporterErrorCode.DEV_REPORT_INVALID_RESPONSE,
    )
    for attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
        try:
            status, response = transport(webhook_url, body, timeout_seconds)
        except TimeoutError:
            last = DeliveryResult(
                DeliveryStatus.NETWORK_TIMEOUT,
                attempt,
                error_code=ReporterErrorCode.DEV_REPORT_NETWORK_TIMEOUT,
            )
        except HTTPError as exc:
            last = DeliveryResult(
                DeliveryStatus.HTTP_ERROR,
                attempt,
                http_status=exc.code,
                error_code=ReporterErrorCode.DEV_REPORT_HTTP_ERROR,
            )
            if exc.code not in {429, 500, 502, 503, 504}:
                return last
        except URLError as exc:
            if isinstance(exc.reason, socket.gaierror):
                last = DeliveryResult(
                    DeliveryStatus.DNS_ERROR,
                    attempt,
                    error_code=ReporterErrorCode.DEV_REPORT_DNS_ERROR,
                )
            else:
                last = DeliveryResult(
                    DeliveryStatus.NETWORK_TIMEOUT,
                    attempt,
                    error_code=ReporterErrorCode.DEV_REPORT_NETWORK_TIMEOUT,
                )
        else:
            if status != 200:
                last = DeliveryResult(
                    DeliveryStatus.HTTP_ERROR,
                    attempt,
                    http_status=status,
                    error_code=ReporterErrorCode.DEV_REPORT_HTTP_ERROR,
                )
                if status not in {429, 500, 502, 503, 504}:
                    return last
            elif response.strip() != b"ok":
                return DeliveryResult(
                    DeliveryStatus.INVALID_RESPONSE,
                    attempt,
                    http_status=status,
                    error_code=ReporterErrorCode.DEV_REPORT_INVALID_RESPONSE,
                )
            else:
                return DeliveryResult(DeliveryStatus.SENT, attempt, http_status=status)
        if attempt < MAX_DELIVERY_ATTEMPTS:
            sleep(0.2 * attempt)
    return last


def archive_report(
    report: DevelopmentProgressReport, archive_root: Path = DEFAULT_ARCHIVE_ROOT
) -> ArchiveResult:
    try:
        redacted = DevelopmentProgressReport.model_validate(
            redact_value(report.model_dump(mode="json"))
        )
        validate_report(redacted)
        archive_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        archive_root.chmod(0o750)
        _set_eom_owner(archive_root)
        timestamp = redacted.timestamp_utc.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = archive_root / f"{timestamp}_{redacted.report_id}.json"
        temporary = archive_root / f".{destination.name}.tmp"
        temporary.write_text(
            json.dumps(redacted.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o640)
        temporary.replace(destination)
        destination.chmod(0o640)
        _set_eom_owner(destination)
        return ArchiveResult(destination)
    except (OSError, ValueError):
        return ArchiveResult(None, ReporterErrorCode.DEV_REPORT_ARCHIVE_FAILED)


def _parse_environment_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid reporter configuration line {number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"EOM_DEV_SLACK_REPORTING_ENABLED", "EOM_DEV_SLACK_WEBHOOK_URL"}:
            raise ValueError(f"unsupported reporter configuration key at line {number}")
        values[key] = value.strip().strip("'").strip('"')
    return values


def _valid_payload(payload: Mapping[str, Any]) -> bool:
    return isinstance(payload.get("text"), str) and isinstance(payload.get("blocks"), list)


def _post(url: str, body: bytes, timeout_seconds: float) -> tuple[int, bytes]:
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(
        request, timeout=timeout_seconds, context=ssl.create_default_context()
    ) as response:
        return response.status, response.read(128)


def _set_eom_owner(path: Path) -> None:
    if os.geteuid() != 0:
        return
    try:
        account = pwd.getpwnam("eom")
        os.chown(path, account.pw_uid, account.pw_gid)
    except (KeyError, OSError):
        return
