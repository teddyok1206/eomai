"""Read-only, host-capacity-fenced maintenance for sequential Codex diagnostics."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from types import TracebackType

from sqlalchemy import Connection, Engine, and_, exists, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.selectable import Exists

from eom_orchestrator.control_models import CodexControlCommandRecord, WorkerLeaseRecord
from eom_orchestrator.control_service import WORKER_HOST_CAPACITY_LOCK_ID, ControlPlaneError
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord, GeneralChatTurnRecord
from eom_orchestrator.models import Base, JobRecord
from eom_orchestrator.worker_systemd import SYSTEMCTL, SYSTEMCTL_ENV

CODEX_PRODUCER_UNITS = (
    "eom-workflow-runner.service",
    "eom-workflow-maintenance.service",
    "eom-general-chat.service",
    "eom-general-chat-worker.service",
    # This broker is not an inference producer. Its stop is an account-enrollment
    # fence; the application also revalidates the pinned binding before each call.
    "eom-codex-auth-broker.service",
)
_PRODUCER_PROPERTIES = frozenset(
    {"Id", "LoadState", "ActiveState", "SubState", "MainPID", "Job", "NeedDaemonReload"}
)
_MAX_UNIT_OUTPUT_BYTES = 64 * 1024
_EXECUTABLE_JOB_STATES = (
    "VALIDATED",
    "QUEUED",
    "CLAIMED",
    "RUNNING",
    "VALIDATING_RESULT",
    "COMMITTING",
)
# A narrow read projection, not a transition/recovery rule. Failed QUEUED attempts
# remain busy because the workflow application supports capacity-queued recovery.
_UNSUCCESSFUL_TERMINAL_STATES = ("FAILED", "CANCELLED")
_LOCK_OWNERSHIP_QUERY = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
    "AND pid = pg_backend_pid() AND granted AND objsubid = 1 "
    "AND classid = :classid AND objid = :objid)"
)


def _systemctl_read(arguments: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            (str(SYSTEMCTL), *arguments),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=5,
            env=SYSTEMCTL_ENV,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_UNIT_UNAVAILABLE", "Codex maintenance unit evidence unavailable"
        ) from exc
    if (
        completed.returncode != 0
        or completed.stderr
        or len(completed.stdout) > _MAX_UNIT_OUTPUT_BYTES
    ):
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_UNIT_UNAVAILABLE", "Codex maintenance unit evidence unavailable"
        )
    try:
        return completed.stdout.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_UNIT_INVALID", "Codex maintenance unit evidence malformed"
        ) from exc


def assert_codex_producers_quiescent() -> None:
    """Observe fixed units only; never stop/start services or clear their failure history."""

    producer_output = _systemctl_read(
        (
            "show",
            "--no-pager",
            "--property=" + ",".join(sorted(_PRODUCER_PROPERTIES)),
            *CODEX_PRODUCER_UNITS,
        )
    )
    observed: set[str] = set()
    for block in producer_output.strip().split("\n\n"):
        properties: dict[str, str] = {}
        for line in block.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in _PRODUCER_PROPERTIES or key in properties:
                raise ControlPlaneError(
                    "CODEX_COMPATIBILITY_UNIT_INVALID", "Codex producer evidence malformed"
                )
            properties[key] = value
        if set(properties) != _PRODUCER_PROPERTIES:
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_UNIT_INVALID", "Codex producer evidence incomplete"
            )
        identity = properties["Id"]
        if identity not in CODEX_PRODUCER_UNITS or identity in observed:
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_UNIT_INVALID", "Codex producer identity differs"
            )
        observed.add(identity)
        if (
            properties["LoadState"] not in {"loaded", "masked"}
            or properties["ActiveState"] != "inactive"
            or properties["SubState"] != "dead"
            or properties["MainPID"] != "0"
            or properties["Job"]
            or properties["NeedDaemonReload"] != "no"
        ):
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_PRODUCER_BUSY", "Codex producers must be stopped first"
            )
    if observed != set(CODEX_PRODUCER_UNITS):
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_UNIT_INVALID", "Codex producer evidence incomplete"
        )
    assert_codex_workers_quiescent()


def assert_codex_workers_quiescent() -> None:
    """Check fixed worker instances before stopping otherwise-idle producers."""

    # This also catches orphan execution/usage/auth/login units absent from DB history,
    # including the support/document-review templates and any unknown worker successor.
    active_workers = _systemctl_read(
        (
            "list-units",
            "--no-pager",
            "--no-legend",
            "--plain",
            "--all",
            "--type=service",
            "--state=active,activating,deactivating,reloading",
            "eom-worker-*.service",
            "eom-worker@*.service",
        )
    )
    if active_workers.strip():
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_WORKER_BUSY", "A fixed Codex worker/helper is still active"
        )


def _executable_jobs_exist() -> Exists:
    jobs = JobRecord.__table__
    steps = Base.metadata.tables.get("workflow_step_runs")
    workflows = Base.metadata.tables.get("workflow_instances")
    commands = Base.metadata.tables.get("workflow_commands")
    if steps is None or workflows is None or commands is None:
        # In an incomplete composition no historical exception can be proven.
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


def _assert_existing_work_absent(connection: Connection) -> None:
    checks = (
        (
            exists().where(WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING"))),
            "CODEX_COMPATIBILITY_LEASE_BUSY",
        ),
        (
            exists().where(CodexControlCommandRecord.state == "PROCESSING"),
            "CODEX_COMPATIBILITY_CONTROL_BUSY",
        ),
        (
            _executable_jobs_exist(),
            "CODEX_COMPATIBILITY_JOB_BUSY",
        ),
        (
            exists().where(GeneralChatCapacityRecord.active_turn_id.is_not(None)),
            "CODEX_COMPATIBILITY_CHAT_BUSY",
        ),
        (
            exists().where(GeneralChatTurnRecord.state.in_(("CLAIMED", "RUNNING", "COMMITTING"))),
            "CODEX_COMPATIBILITY_CHAT_BUSY",
        ),
    )
    for predicate, code in checks:
        busy = connection.scalar(select(predicate))
        if type(busy) is not bool:
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_DATABASE_INVALID", "Codex maintenance evidence invalid"
            )
        if busy:
            raise ControlPlaneError(code, "Existing Codex work prevents maintenance")


def assert_codex_compatibility_database_quiescent(engine: Engine) -> None:
    """Read-only pre-stop evidence, not a capacity reservation or permission to execute."""

    if engine.dialect.name != "postgresql":
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_BACKEND_UNSUPPORTED", "Codex maintenance requires PostgreSQL"
        )
    try:
        with engine.connect() as connection:
            _assert_existing_work_absent(connection)
            connection.commit()
    except SQLAlchemyError as exc:
        raise ControlPlaneError(
            "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE", "Codex maintenance evidence unavailable"
        ) from exc


class CodexCompatibilityMaintenance:
    """Hold the existing host lock across short, read-only diagnostic transactions.

    The operator owns service stop/start. This fence grants no ordinary worker lease,
    capability admission, runtime installation or permission to execute concurrently.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        host_reader: Callable[[], None] = assert_codex_producers_quiescent,
    ) -> None:
        self._engine = engine
        self._host_reader = host_reader
        self._connection: Connection | None = None

    def __enter__(self) -> CodexCompatibilityMaintenance:
        if self._connection is not None:
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_FENCE_ACTIVE", "Codex maintenance fence already active"
            )
        if self._engine.dialect.name != "postgresql":
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_BACKEND_UNSUPPORTED", "Codex maintenance requires PostgreSQL"
            )
        try:
            connection = self._engine.connect()
        except SQLAlchemyError as exc:
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE", "Codex maintenance session unavailable"
            ) from exc
        try:
            locked = connection.scalar(
                select(func.pg_try_advisory_lock(WORKER_HOST_CAPACITY_LOCK_ID))
            )
            connection.commit()
            if locked is not True:
                raise ControlPlaneError(
                    "CODEX_COMPATIBILITY_FENCE_BUSY", "Codex host capacity is already reserved"
                )
            self._connection = connection
            self.assert_quiescent()
        except BaseException as exc:
            if self._connection is not None:
                self._release_connection(preserve_error=True)
            else:
                # If lock acquisition/commit was uncertain, discard the physical
                # session rather than return a possibly locked connection to the pool.
                connection.invalidate()
                connection.close()
            if isinstance(exc, SQLAlchemyError):
                raise ControlPlaneError(
                    "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE",
                    "Codex maintenance lock observation unavailable",
                ) from exc
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._release_connection(preserve_error=exc is not None)

    def assert_quiescent(self) -> None:
        """Recheck every launch; a lost host session never authorizes another probe."""

        connection = self._connection
        if connection is None or connection.closed or connection.invalidated:
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_FENCE_LOST", "Codex maintenance host fence unavailable"
            )
        try:
            owned = connection.scalar(
                _LOCK_OWNERSHIP_QUERY,
                {
                    "classid": WORKER_HOST_CAPACITY_LOCK_ID >> 32,
                    "objid": WORKER_HOST_CAPACITY_LOCK_ID & 0xFFFFFFFF,
                },
            )
            if owned is not True:
                raise ControlPlaneError(
                    "CODEX_COMPATIBILITY_FENCE_LOST", "Codex maintenance host fence not held"
                )
            _assert_existing_work_absent(connection)
            connection.commit()
        except SQLAlchemyError as exc:
            try:
                connection.rollback()
            except SQLAlchemyError:
                connection.invalidate()
            raise ControlPlaneError(
                "CODEX_COMPATIBILITY_DATABASE_UNAVAILABLE", "Codex maintenance evidence unavailable"
            ) from exc
        except BaseException:
            try:
                connection.rollback()
            except SQLAlchemyError:
                connection.invalidate()
            raise
        self._host_reader()

    def _release_connection(self, *, preserve_error: bool) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            if connection.closed or connection.invalidated:
                raise ControlPlaneError(
                    "CODEX_COMPATIBILITY_FENCE_LOST", "Codex maintenance host fence unavailable"
                )
            connection.rollback()
            released = connection.scalar(
                select(func.pg_advisory_unlock(WORKER_HOST_CAPACITY_LOCK_ID))
            )
            connection.commit()
            if released is not True:
                raise ControlPlaneError(
                    "CODEX_COMPATIBILITY_FENCE_LOST", "Codex maintenance host fence not held"
                )
        except BaseException as exc:
            connection.invalidate()
            if not preserve_error:
                if isinstance(exc, (SQLAlchemyError, ControlPlaneError)):
                    raise ControlPlaneError(
                        "CODEX_COMPATIBILITY_FENCE_LOST", "Codex maintenance fence release failed"
                    ) from exc
                raise
        finally:
            connection.close()
