from __future__ import annotations

import json
import socket
import subprocess
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from eom_dev_reporter import cli
from eom_dev_reporter.git_context import collect_git_context
from eom_dev_reporter.models import (
    DevelopmentProgressReport,
    ReportSchemaError,
    ReportStatus,
    new_report_id,
    validate_report,
)
from eom_dev_reporter.redaction import REDACTED, redact_text, redact_value
from eom_dev_reporter.renderer import render_payload
from eom_dev_reporter.sender import (
    ArchiveResult,
    DeliveryResult,
    DeliveryStatus,
    ReporterConfig,
    ReporterErrorCode,
    archive_report,
    load_reporter_config,
    send_webhook,
    valid_webhook_url,
)
from pydantic import ValidationError

SLACK_WEBHOOK_ORIGIN = "https://" + "hooks.slack.com"
WEBHOOK = f"{SLACK_WEBHOOK_ORIGIN}/services/T000/B000/secret-value"


def _report(**overrides: object) -> DevelopmentProgressReport:
    values: dict[str, object] = {
        "report_id": "devreport_0123456789abcdef0123456789abcdef",
        "repository": "/home/eom/EOM",
        "branch": "feat/workflow-engine-v0",
        "head_commit": "a" * 40,
        "working_tree_clean": False,
        "status": ReportStatus.IN_PROGRESS,
        "phase": "workflow-definition",
        "summary": "Domain-neutral workflow compiler implementation",
        "completed": ("Baseline tests PASS",),
        "in_progress": ("Definition compiler",),
        "next": ("Migration",),
        "blockers": (),
        "tests": ("unit=PASS",),
        "changed_file_count": 3,
        "diff_stat": ("3 files changed",),
        "timestamp_utc": datetime(2026, 8, 15, tzinfo=UTC),
    }
    values.update(overrides)
    return DevelopmentProgressReport.model_validate(values)


def test_report_passes_json_schema_and_pydantic() -> None:
    report = _report()
    validate_report(report)
    assert report.report_version == "1.0"


def test_report_status_enum_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        _report(status="UNKNOWN")


def test_report_id_is_unique_and_well_formed() -> None:
    first = new_report_id()
    second = new_report_id()
    assert first.startswith("devreport_")
    assert len(first) == 42
    assert first != second


def test_report_requires_utc_timestamp() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        _report(timestamp_utc="2026-08-15T09:00:00+09:00")


def test_schema_rejects_extra_field() -> None:
    value = _report().model_dump(mode="json")
    value["secret"] = "not allowed"
    with pytest.raises(ReportSchemaError, match="Additional properties"):
        validate_report(value)


@pytest.mark.parametrize("dirty", [False, True])
def test_git_context_collects_bounded_clean_or_dirty_state(
    monkeypatch: pytest.MonkeyPatch, dirty: bool
) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(args[1:])
        outputs = {
            ("rev-parse", "--show-toplevel"): "/home/eom/EOM\n",
            ("branch", "--show-current"): "feat/workflow-engine-v0\n",
            ("rev-parse", "HEAD"): f"{'a' * 40}\n",
            ("status", "--porcelain=v1", "--untracked-files=normal"): (
                " M README.md\n?? local.txt\n" if dirty else ""
            ),
            ("diff", "--stat", "--stat-count=10"): " README.md | 1 +\n",
            ("diff", "--cached", "--stat", "--stat-count=10"): "",
        }
        return subprocess.CompletedProcess(args, 0, outputs[command], "")

    monkeypatch.setattr("eom_dev_reporter.git_context.subprocess.run", fake_run)
    context = collect_git_context(Path("/home/eom/EOM"))
    assert context.working_tree_clean is not dirty
    assert context.changed_file_count == (2 if dirty else 0)
    assert context.diff_stat == ("README.md | 1 +",)


def test_secret_and_webhook_redaction_is_recursive() -> None:
    fake_token = "xox" + "b-secret-token"
    value = {"summary": f"do not send {WEBHOOK}", "items": [fake_token]}
    redacted = redact_value(value)
    assert WEBHOOK not in json.dumps(redacted)
    assert fake_token not in json.dumps(redacted)
    assert REDACTED in json.dumps(redacted)


def test_renderer_has_fallback_text_and_blocks_without_sensitive_value() -> None:
    payload = render_payload(_report(summary=f"configured at {WEBHOOK}"))
    encoded = json.dumps(payload)
    assert payload["text"].startswith("[EOM")
    assert payload["blocks"]
    assert WEBHOOK not in encoded
    assert "secret-value" not in encoded


def test_disabled_and_missing_reporter_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EOM_DEV_SLACK_REPORTING_ENABLED", raising=False)
    monkeypatch.delenv("EOM_DEV_SLACK_WEBHOOK_URL", raising=False)
    missing = load_reporter_config(tmp_path / "missing.env")
    assert missing == ReporterConfig(enabled=False, webhook_url=None)
    result = send_webhook(render_payload(_report()), missing)
    assert result.status == DeliveryStatus.NOT_CONFIGURED
    disabled = send_webhook(
        render_payload(_report()), ReporterConfig(enabled=False, webhook_url=WEBHOOK)
    )
    assert disabled.status == DeliveryStatus.DISABLED


@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://" + "hooks.slack.com/services/T/B/C",
        "https://example.com/services/T/B/C",
        "https://hooks.slack.com/not-services/T/B/C",
        SLACK_WEBHOOK_ORIGIN + "/services/T/B/C?leak=yes",
    ],
)
def test_invalid_webhook_url_is_rejected(url: str | None) -> None:
    assert not valid_webhook_url(url)


def test_dry_run_cli_does_not_send(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "archive_report", lambda _report: ArchiveResult(Path("/tmp/report")))
    monkeypatch.setattr(
        cli,
        "send_webhook",
        lambda *_args, **_kwargs: pytest.fail("dry-run attempted delivery"),
    )
    result = cli.main(
        [
            "send",
            "--dry-run",
            "--no-git-context",
            "--status",
            "TESTING",
            "--phase",
            "unit",
            "--summary",
            "Reporter dry run",
        ]
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["delivery_status"] == "DRY_RUN"
    assert output["component"] == "dev_reporter"
    assert output["report_status"] == "TESTING"
    assert output["phase"] == "unit"
    assert output["timestamp"].endswith("Z")


def test_http_200_ok_is_success() -> None:
    result = send_webhook(
        render_payload(_report()),
        ReporterConfig(True, WEBHOOK),
        post=lambda _url, _body, _timeout: (200, b"ok"),
    )
    assert result == DeliveryResult(DeliveryStatus.SENT, 1, 200)


@pytest.mark.parametrize("status", [400, 403, 404])
def test_non_retryable_http_errors_only_attempt_once(status: int) -> None:
    calls = 0

    def post(_url: str, _body: bytes, _timeout: float) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        raise HTTPError("redacted", status, "failure", Message(), None)

    result = send_webhook(
        render_payload(_report()), ReporterConfig(True, WEBHOOK), post=post, sleep=lambda _: None
    )
    assert result.status == DeliveryStatus.HTTP_ERROR
    assert result.http_status == status
    assert calls == 1


def test_invalid_response_is_not_retried() -> None:
    calls = 0

    def post(_url: str, _body: bytes, _timeout: float) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        return 200, b"unexpected"

    result = send_webhook(render_payload(_report()), ReporterConfig(True, WEBHOOK), post=post)
    assert result.status == DeliveryStatus.INVALID_RESPONSE
    assert calls == 1


def test_timeout_is_retried_with_a_finite_limit() -> None:
    calls = 0

    def post(_url: str, _body: bytes, _timeout: float) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        raise TimeoutError

    result = send_webhook(
        render_payload(_report()), ReporterConfig(True, WEBHOOK), post=post, sleep=lambda _: None
    )
    assert result.status == DeliveryStatus.NETWORK_TIMEOUT
    assert result.attempts == 3
    assert calls == 3


def test_retryable_network_failure_can_recover() -> None:
    calls = 0

    def post(_url: str, _body: bytes, _timeout: float) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError(socket.gaierror())
        return 200, b"ok"

    result = send_webhook(
        render_payload(_report()), ReporterConfig(True, WEBHOOK), post=post, sleep=lambda _: None
    )
    assert result.status == DeliveryStatus.SENT
    assert result.attempts == 2


def test_malformed_payload_is_not_retried() -> None:
    calls = 0

    def post(_url: str, _body: bytes, _timeout: float) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        return 200, b"ok"

    result = send_webhook({}, ReporterConfig(True, WEBHOOK), post=post)
    assert result.status == DeliveryStatus.INVALID_PAYLOAD
    assert calls == 0


def test_archive_is_redacted_and_mode_0640(tmp_path: Path) -> None:
    report = _report(summary=f"never archive {WEBHOOK}")
    result = archive_report(report, tmp_path / "reports")
    assert result.path is not None
    assert result.path.stat().st_mode & 0o777 == 0o640
    content = result.path.read_text(encoding="utf-8")
    assert WEBHOOK not in content
    validate_report(json.loads(content))


def test_archive_failure_is_non_blocking(tmp_path: Path) -> None:
    root = tmp_path / "not-a-directory"
    root.write_text("occupied", encoding="utf-8")
    result = archive_report(_report(), root)
    assert result.path is None
    assert result.error_code == ReporterErrorCode.DEV_REPORT_ARCHIVE_FAILED


@pytest.mark.parametrize(("strict", "expected"), [(False, 0), (True, 1)])
def test_cli_delivery_failure_only_exits_nonzero_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch, strict: bool, expected: int
) -> None:
    monkeypatch.setattr(cli, "archive_report", lambda _report: ArchiveResult(None))
    monkeypatch.setattr(
        cli,
        "send_webhook",
        lambda *_args, **_kwargs: DeliveryResult(
            DeliveryStatus.HTTP_ERROR,
            1,
            403,
            ReporterErrorCode.DEV_REPORT_HTTP_ERROR,
        ),
    )
    args = [
        "send",
        "--no-git-context",
        "--status",
        "FAILED",
        "--phase",
        "test",
        "--summary",
        "delivery failed",
    ]
    if strict:
        args.append("--strict")
    assert cli.main(args) == expected


def test_explicit_secret_redaction() -> None:
    assert redact_text("prefix abc123 suffix", ("abc123",)) == f"prefix {REDACTED} suffix"
