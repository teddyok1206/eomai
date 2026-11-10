"""Shared read-only distinction between executable jobs and sealed failed history."""

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.sql.selectable import Exists

from eom_orchestrator.models import Base, JobRecord

_EXECUTABLE_JOB_STATES = (
    "VALIDATED",
    "QUEUED",
    "CLAIMED",
    "RUNNING",
    "VALIDATING_RESULT",
    "COMMITTING",
)
# Failed QUEUED attempts remain busy: supported capacity recovery can resume them.
_UNSUCCESSFUL_TERMINAL_STATES = ("FAILED", "CANCELLED")


def executable_jobs_exist() -> Exists:
    """Filterable EXISTS using exact indexed Workflow links; never modifies history.

    Physical-unit and held-lease checks remain independent admission requirements.
    Missing composition, dangling/mixed links and active commands all fail closed.
    """
    jobs = JobRecord.__table__
    steps = Base.metadata.tables.get("workflow_step_runs")
    workflows = Base.metadata.tables.get("workflow_instances")
    commands = Base.metadata.tables.get("workflow_commands")
    if steps is None or workflows is None or commands is None:
        return exists().where(jobs.c.status.in_(_EXECUTABLE_JOB_STATES))
    linked = steps.alias("maintenance_linked_steps")
    parent = workflows.alias("maintenance_parent")
    command = commands.alias("maintenance_parent_command")
    exact_link = exists().where(
        linked.c.platform_job_id == jobs.c.job_id,
        linked.c.workflow_id == jobs.c.request["workflow_id"].astext,
        linked.c.step_run_id == jobs.c.request["step_run_id"].astext,
    )
    unsafe_link = (
        select(linked.c.step_run_id)
        .select_from(linked.outerjoin(parent, parent.c.workflow_id == linked.c.workflow_id))
        .where(
            linked.c.platform_job_id == jobs.c.job_id,
            or_(
                linked.c.state.not_in(_UNSUCCESSFUL_TERMINAL_STATES),
                parent.c.workflow_id.is_(None),
                parent.c.state.not_in(_UNSUCCESSFUL_TERMINAL_STATES),
                linked.c.workflow_id != jobs.c.request["workflow_id"].astext,
                linked.c.step_run_id != jobs.c.request["step_run_id"].astext,
            ),
        )
        .exists()
    )
    active_parent_command = (
        select(command.c.command_id)
        .select_from(command.join(linked, command.c.workflow_id == linked.c.workflow_id))
        .where(
            linked.c.platform_job_id == jobs.c.job_id,
            command.c.state.in_(("PENDING", "LEASED", "PROCESSING")),
        )
        .exists()
    )
    historical_terminal_child = and_(
        jobs.c.status.in_(("CLAIMED", "RUNNING")),
        exact_link,
        ~unsafe_link,
        ~active_parent_command,
    )
    return exists().where(jobs.c.status.in_(_EXECUTABLE_JOB_STATES), ~historical_terminal_child)
