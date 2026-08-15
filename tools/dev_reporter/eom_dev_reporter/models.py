"""Validated model for development-only progress reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPORT_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/dev/development-progress-report.schema.json"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]


class ReportStatus(StrEnum):
    STARTED = "STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    RECOVERED = "RECOVERED"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DevelopmentProgressReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    report_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^devreport_[0-9a-f]{32}$")
    project: Literal["EOM"] = "EOM"
    repository: str = Field(min_length=1, max_length=256)
    branch: str = Field(min_length=1, max_length=128)
    head_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    working_tree_clean: bool
    status: ReportStatus
    phase: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=1000)
    completed: tuple[str, ...] = Field(default=(), max_length=20)
    in_progress: tuple[str, ...] = Field(default=(), max_length=20)
    next: tuple[str, ...] = Field(default=(), max_length=20)
    blockers: tuple[str, ...] = Field(default=(), max_length=20)
    tests: tuple[str, ...] = Field(default=(), max_length=20)
    changed_file_count: int = Field(ge=0)
    diff_stat: tuple[str, ...] = Field(default=(), max_length=10)
    timestamp_utc: UtcDatetime


class ReportSchemaError(ValueError):
    pass


def load_report_schema() -> dict[str, Any]:
    raw: object = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ReportSchemaError("development report schema is not an object")
    Draft202012Validator.check_schema(raw)
    return raw


def validate_report(report: DevelopmentProgressReport | dict[str, Any]) -> None:
    data = (
        report.model_dump(mode="json") if isinstance(report, DevelopmentProgressReport) else report
    )
    validator = Draft202012Validator(load_report_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ReportSchemaError(f"development report at {path}: {error.message}")


def new_report_id() -> str:
    return f"devreport_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(UTC)
