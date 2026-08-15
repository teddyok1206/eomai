"""Short Slack webhook payload rendering."""

from __future__ import annotations

from typing import Any

from eom_dev_reporter.models import DevelopmentProgressReport, validate_report
from eom_dev_reporter.redaction import redact_text, redact_value

MAX_LIST_ITEMS = 8
MAX_ITEM_LENGTH = 180


def render_payload(report: DevelopmentProgressReport) -> dict[str, Any]:
    validate_report(report)
    clean = DevelopmentProgressReport.model_validate(redact_value(report.model_dump(mode="json")))
    title = f"[EOM 개발 보고] Workflow Engine V0 - {clean.status}"
    fallback = _truncate(f"{title} | {clean.phase} | {clean.summary}", 500)
    sections = [
        _section("Phase", [clean.phase]),
        _section("Summary", [clean.summary]),
        _section("Completed", clean.completed),
        _section("In progress", clean.in_progress),
        _section("Next", clean.next),
        _section("Tests", clean.tests),
        _section("Blockers", clean.blockers or ("None",)),
        _section(
            "Git",
            (
                f"Branch: {clean.branch}",
                f"HEAD: {clean.head_commit[:12]}",
                f"Working tree: {'clean' if clean.working_tree_clean else 'modified'}",
                f"Changed files: {clean.changed_file_count}",
            ),
        ),
        _section("UTC", [clean.timestamp_utc.isoformat().replace("+00:00", "Z")]),
    ]
    return {
        "text": fallback,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
            *(section for section in sections if section is not None),
        ],
    }


def _section(title: str, items: tuple[str, ...] | list[str]) -> dict[str, Any] | None:
    if not items:
        return None
    rendered = "\n".join(
        f"• {_escape(_truncate(item, MAX_ITEM_LENGTH))}" for item in items[:MAX_LIST_ITEMS]
    )
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": _truncate(f"*{title}*\n{rendered}", 2900)},
    }


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(value: str, limit: int) -> str:
    clean = redact_text(value).replace("\x00", "")
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."
