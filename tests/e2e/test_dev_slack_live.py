from __future__ import annotations

import os
from pathlib import Path

import pytest
from eom_dev_reporter.git_context import collect_git_context
from eom_dev_reporter.models import DevelopmentProgressReport, ReportStatus, new_report_id, utc_now
from eom_dev_reporter.renderer import render_payload
from eom_dev_reporter.sender import (
    DeliveryStatus,
    archive_report,
    load_reporter_config,
    send_webhook,
)

pytestmark = pytest.mark.dev_slack_live


def test_live_development_webhook_delivery() -> None:
    if os.environ.get("EOM_RUN_DEV_SLACK_LIVE") != "1":
        pytest.skip("set EOM_RUN_DEV_SLACK_LIVE=1 to run the live development Slack test")
    context = collect_git_context(Path("/home/eom/EOM"))
    report = DevelopmentProgressReport(
        report_id=new_report_id(),
        repository=context.repository,
        branch=context.branch,
        head_commit=context.head_commit,
        working_tree_clean=context.working_tree_clean,
        status=ReportStatus.TESTING,
        phase="dev-slack-live",
        summary="EOM development Slack reporter live acceptance test",
        completed=("Schema and dry-run validation",),
        in_progress=(),
        next=("Workflow Engine V0 implementation",),
        blockers=(),
        tests=("dev_slack_live=running",),
        changed_file_count=context.changed_file_count,
        diff_stat=context.diff_stat,
        timestamp_utc=utc_now(),
    )
    archived = archive_report(report)
    delivered = send_webhook(render_payload(report), load_reporter_config())
    assert archived.path is not None
    assert delivered.status == DeliveryStatus.SENT
