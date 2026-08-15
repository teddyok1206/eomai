"""CLI for rendering and sending bounded development reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from eom_dev_reporter.doctor import run_reporter_doctor
from eom_dev_reporter.git_context import GitContext, collect_git_context
from eom_dev_reporter.models import (
    DevelopmentProgressReport,
    ReportSchemaError,
    ReportStatus,
    new_report_id,
    utc_now,
    validate_report,
)
from eom_dev_reporter.redaction import redact_value
from eom_dev_reporter.renderer import render_payload
from eom_dev_reporter.sender import (
    DeliveryResult,
    DeliveryStatus,
    ReporterErrorCode,
    archive_report,
    load_reporter_config,
    send_webhook,
)

REPOSITORY = Path("/home/eom/EOM")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eom-dev-report")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")

    render = subparsers.add_parser("render")
    render.add_argument("--report-file", type=Path, required=True)

    send = subparsers.add_parser("send")
    send.add_argument("--dry-run", action="store_true")
    send.add_argument("--strict", action="store_true")
    send.add_argument("--no-git-context", action="store_true")
    send.add_argument("--report-file", type=Path)
    send.add_argument("--status", choices=[status.value for status in ReportStatus])
    send.add_argument("--phase")
    send.add_argument("--summary")
    send.add_argument("--completed", action="append", default=[])
    send.add_argument("--in-progress", action="append", default=[])
    send.add_argument("--next", action="append", default=[])
    send.add_argument("--blocker", action="append", default=[])
    send.add_argument("--test", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor()
        if args.command == "render":
            report = _load_report(args.report_file)
            _emit(render_payload(report))
            return 0
        if args.command == "send":
            report = _load_report(args.report_file) if args.report_file else _build_report(args)
            return _send(report, dry_run=args.dry_run, strict=args.strict)
    except (OSError, ValueError, ValidationError, ReportSchemaError) as exc:
        _emit(
            {
                "ok": False,
                "error_code": ReporterErrorCode.DEV_REPORT_SCHEMA_INVALID,
                "error": type(exc).__name__,
            }
        )
        return 1
    return 1


def _doctor() -> int:
    checks = run_reporter_doctor(REPOSITORY)
    required_passed = all(check.passed for check in checks if check.required)
    operational_ready = all(check.passed for check in checks)
    _emit(
        {
            "required_passed": required_passed,
            "operational_ready": operational_ready,
            "checks": [check.as_dict() for check in checks],
        }
    )
    return 0 if required_passed else 1


def _build_report(args: argparse.Namespace) -> DevelopmentProgressReport:
    if not args.status or not args.phase or not args.summary:
        raise ValueError("--status, --phase, and --summary are required without --report-file")
    context = (
        GitContext(str(REPOSITORY), "unknown", "unknown", False, 0, ())
        if args.no_git_context
        else collect_git_context(REPOSITORY)
    )
    report = DevelopmentProgressReport(
        report_id=new_report_id(),
        repository=context.repository,
        branch=context.branch,
        head_commit=context.head_commit,
        working_tree_clean=context.working_tree_clean,
        status=args.status,
        phase=args.phase,
        summary=args.summary,
        completed=tuple(args.completed),
        in_progress=tuple(args.in_progress),
        next=tuple(args.next),
        blockers=tuple(args.blocker),
        tests=tuple(args.test),
        changed_file_count=context.changed_file_count,
        diff_stat=context.diff_stat,
        timestamp_utc=utc_now(),
    )
    validate_report(report)
    return report


def _load_report(path: Path) -> DevelopmentProgressReport:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ReportSchemaError("report file is not an object")
    validate_report(raw)
    return DevelopmentProgressReport.model_validate(raw)


def _send(report: DevelopmentProgressReport, *, dry_run: bool, strict: bool) -> int:
    payload = render_payload(report)
    archive = archive_report(report)
    if dry_run:
        delivery = DeliveryResult(DeliveryStatus.DRY_RUN, 0)
    else:
        delivery = send_webhook(payload, load_reporter_config())
    output: dict[str, Any] = {
        "ok": delivery.succeeded,
        "report_id": report.report_id,
        "delivery_status": delivery.status,
        "attempts": delivery.attempts,
        "http_status": delivery.http_status,
        "error_code": delivery.error_code,
        "archive_status": "SAVED" if archive.path else "FAILED",
        "archive_path": str(archive.path) if archive.path else None,
        "archive_error_code": archive.error_code,
    }
    if dry_run:
        output["payload"] = redact_value(payload)
    _emit(output)
    return 1 if strict and not delivery.succeeded else 0


def _emit(value: object) -> None:
    sys.stdout.write(
        json.dumps(redact_value(value), ensure_ascii=False, indent=2, default=str) + "\n"
    )
