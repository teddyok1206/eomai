"""Non-secret diagnostics for the development reporter."""

from __future__ import annotations

import socket
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from eom_dev_reporter.git_context import collect_git_context
from eom_dev_reporter.models import REPORT_SCHEMA_PATH, load_report_schema
from eom_dev_reporter.redaction import masked_webhook_url
from eom_dev_reporter.sender import DEFAULT_SECRET_PATH, load_reporter_config, valid_webhook_url


@dataclass(frozen=True)
class ReporterDoctorCheck:
    name: str
    passed: bool
    required: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def run_reporter_doctor(
    repository: Path, secret_path: Path = DEFAULT_SECRET_PATH
) -> list[ReporterDoctorCheck]:
    checks: list[ReporterDoctorCheck] = []
    checks.append(ReporterDoctorCheck("reporter_code", True, True, "loaded"))
    try:
        load_report_schema()
        checks.append(ReporterDoctorCheck("schema", True, True, str(REPORT_SCHEMA_PATH)))
    except Exception as exc:
        checks.append(ReporterDoctorCheck("schema", False, True, type(exc).__name__))

    secret_exists = secret_path.is_file()
    checks.append(ReporterDoctorCheck("secret_file_exists", secret_exists, False, str(secret_path)))
    if secret_exists:
        mode = stat.S_IMODE(secret_path.stat().st_mode)
        permission_ok = mode in {0o600, 0o640}
        checks.append(
            ReporterDoctorCheck("secret_file_permission", permission_ok, False, oct(mode))
        )
    else:
        checks.append(ReporterDoctorCheck("secret_file_permission", False, False, "not present"))

    try:
        config = load_reporter_config(secret_path)
        configured = valid_webhook_url(config.webhook_url)
        checks.append(
            ReporterDoctorCheck(
                "enabled_flag", config.enabled, False, "enabled" if config.enabled else "disabled"
            )
        )
        checks.append(
            ReporterDoctorCheck(
                "webhook_configured",
                configured,
                False,
                masked_webhook_url(configured),
            )
        )
        if configured:
            try:
                socket.getaddrinfo("hooks.slack.com", 443, type=socket.SOCK_STREAM)
                dns_ok = True
                dns_detail = "resolved"
            except socket.gaierror:
                dns_ok = False
                dns_detail = "resolution failed"
        else:
            dns_ok = False
            dns_detail = "skipped: webhook not configured"
        checks.append(ReporterDoctorCheck("network_dns", dns_ok, False, dns_detail))
    except (OSError, ValueError) as exc:
        checks.extend(
            (
                ReporterDoctorCheck("enabled_flag", False, False, type(exc).__name__),
                ReporterDoctorCheck("webhook_configured", False, False, "invalid configuration"),
                ReporterDoctorCheck("network_dns", False, False, "skipped"),
            )
        )

    try:
        context = collect_git_context(repository)
        checks.append(ReporterDoctorCheck("git_repository", True, True, context.repository))
    except Exception as exc:
        checks.append(ReporterDoctorCheck("git_repository", False, True, type(exc).__name__))
    return checks
