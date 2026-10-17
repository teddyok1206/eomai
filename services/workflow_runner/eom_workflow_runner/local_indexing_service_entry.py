"""Fixed installed-unit entry; no repository, login, external API or Codex slot."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_workflow_runner.local_indexing_service_runtime import LocalIndexingServiceRuntime

_RELEASES = Path("/opt/eom/embedding-owner-releases")
_RUNTIME_CONFIGURATION = Path("/etc/eom/local-indexing-runtime.json")


def _installed_site() -> Path:
    entry = Path(__file__)
    site, release = entry.parent.parent, entry.parent.parent.parent
    if (
        not sys.flags.isolated
        or not sys.dont_write_bytecode
        or sys.argv != [str(entry)]
        or entry.name != "local_indexing_service_entry.py"
        or entry.parent.name != "eom_workflow_runner"
        or site.name != "site-packages"
        or release.parent != _RELEASES
        or re.fullmatch(r"[0-9a-f]{40}", release.name) is None
    ):
        raise ValueError("LOCAL_INDEXING_SERVICE_INSTALLATION_UNAVAILABLE")
    for parent in entry.parents:
        value = parent.lstat()
        if (
            not stat.S_ISDIR(value.st_mode)
            or parent.is_symlink()
            or value.st_uid != 0
            or value.st_mode & 0o022
        ):
            raise ValueError("LOCAL_INDEXING_SERVICE_INSTALLATION_UNAVAILABLE")
    metadata = entry.lstat()
    if (
        entry.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
        or metadata.st_nlink != 1
    ):
        raise ValueError("LOCAL_INDEXING_SERVICE_INSTALLATION_UNAVAILABLE")
    return site


def _emit(event: str, **metadata: str | int | None) -> None:
    print(
        json.dumps(
            {"timestamp": datetime.now(UTC).isoformat(), "event": event, **metadata},
            sort_keys=True,
        ),
        flush=True,
    )


def _failure_detail(error: Exception) -> dict[str, str | int | None]:
    """Bounded code/site metadata only; never exception messages, locals or a full trace."""
    current: BaseException = error
    seen = {id(current)}
    for _ in range(4):
        related = current.__cause__ or current.__context__
        if related is None or id(related) in seen:
            break
        seen.add(id(related))
        current = related
    code = getattr(current, "code", None)
    if type(code) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", code) is None:
        code = None
    site = None
    entry_site = None
    frame = current.__traceback__
    while frame is not None:
        module = frame.tb_frame.f_globals.get("__name__")
        if type(module) is str and re.fullmatch(r"eom_[a-z0-9_.]{1,120}", module):
            site = f"{module}:{frame.tb_lineno}"
            if entry_site is None:
                entry_site = site
        frame = frame.tb_next
    result: dict[str, str | int | None] = {
        "cause_type": type(current).__name__,
        "cause_code": code,
        "cause_site": site,
    }
    if entry_site is not None:
        result["cause_entry_site"] = entry_site
    for attribute, pattern in (
        ("artifact_id", r"artifact_[0-9a-f]{32}"),
        ("artifact_revision_id", r"rev_[0-9a-f]{32}"),
    ):
        value = getattr(current, attribute, None)
        if type(value) is str and re.fullmatch(pattern, value):
            result["cause_" + attribute] = value
    return result


def serve_local_indexing(runtime: LocalIndexingServiceRuntime, stop: Event) -> None:
    """Round-robin exact namespaces; each drains its queue before new discovery."""
    from eom_workflow_runner.native_cpu_scheduling_read import (
        NativeCpuSchedulingReadUnavailable,
        should_defer_background_cpu_claim,
    )

    deadlines = [0.0] * len(runtime.namespaces)
    last: list[tuple[object, ...] | None] = [None] * len(runtime.namespaces)
    cursor = 0
    deferred: str | None = None
    while not stop.is_set():
        try:
            reason = "ACTIVE_QUERY" if should_defer_background_cpu_claim(runtime.engine) else None
        except NativeCpuSchedulingReadUnavailable:
            reason = "OBSERVATION_UNAVAILABLE"
        if reason is not None:
            if reason != deferred:
                _emit("LOCAL_INDEXING_CPU_ADMISSION_DEFERRED", state=reason)
            deferred = reason
            stop.wait(5.0)
            continue
        if deferred is not None:
            _emit("LOCAL_INDEXING_CPU_ADMISSION_RESUMED", state="READY")
            deferred = None
        index = cursor
        cursor = (cursor + 1) % len(runtime.namespaces)
        namespace = runtime.namespaces[index]
        command = namespace.runner.run_once()
        if command is not None:
            _emit(
                "LOCAL_INDEXING_COMMAND_OBSERVED",
                workflow_id=command.workflow_id,
                command_id=command.command_id,
                state=command.state,
                view=namespace.namespace.view,
            )
            continue
        if stop.is_set():
            break
        now = time.monotonic()
        if now >= deadlines[index]:
            observed = namespace.reconciliation.run_once()
            signature = (
                observed.state,
                observed.graph_snapshot_revision_id,
                observed.missing_binding_count,
                observed.index_refresh_reason,
                observed.missing_report_revision_ids,
                observed.workflow_id,
            )
            if signature != last[index]:
                _emit(
                    "LOCAL_INDEXING_RECONCILIATION_OBSERVED",
                    state=observed.state.value,
                    graph_snapshot_revision_id=observed.graph_snapshot_revision_id,
                    eligible_sources=observed.eligible_source_count,
                    missing_reports=len(observed.missing_report_revision_ids),
                    unavailable_views=observed.unavailable_view_count,
                    missing_bindings=observed.missing_binding_count,
                    selected_targets=observed.selected_target_count,
                    index_refresh_reason=observed.index_refresh_reason,
                    workflow_id=observed.workflow_id,
                    command_id=observed.command_id,
                    view=namespace.namespace.view,
                )
                last[index] = signature
            deadlines[index] = time.monotonic() + runtime.configuration.poll_interval_seconds
            # A newly submitted command gets an immediate iteration. No target
            # list is scanned or claimed independently of the existing Runner.
            if observed.workflow_id is not None and observed.state.value == "QUEUED":
                continue
        stop.wait(min(5.0, max(0.1, min(deadlines) - time.monotonic())))


def main() -> int:
    capture = None
    runtime = None
    try:
        site = _installed_site()
        sys.path.insert(0, str(site))
        from eom_identity_service.local_indexing_runtime import (
            LocalIndexingRuntimePin,
            capture_local_indexing_runtime,
        )
        from eom_operator_identity import parse_local_indexing_runtime_configuration

        # Preliminary bounded metadata only. The actual capture below independently
        # verifies root ownership, exact bytes, unit/process, wheels and file epochs.
        with _RUNTIME_CONFIGURATION.open("rb") as stream:
            raw = stream.read(4097)
        selected = parse_local_indexing_runtime_configuration(raw)
        pin = LocalIndexingRuntimePin(
            selected.service,
            selected.runtime_source_commit,
            "sha256:" + hashlib.sha256(raw).hexdigest(),
        )
        capture = capture_local_indexing_runtime(pin)
        from eom_catalog_service.inference_transfer_read_timing import configure_read_stage_logging

        from eom_workflow_runner.local_indexing_service_runtime import (
            build_local_indexing_service_runtime,
        )

        stop = Event()
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
        configure_read_stage_logging()
        runtime = build_local_indexing_service_runtime(capture, pin)
        _emit("LOCAL_INDEXING_SERVICE_STARTED", pid=os.getpid())
        serve_local_indexing(runtime, stop)
        return 0
    except Exception as error:
        code = getattr(error, "code", None)
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", code) is None:
            code = "LOCAL_INDEXING_SERVICE_UNAVAILABLE"
        # Never print exception text/tracebacks: SQL/HTTP exceptions can carry
        # credentials or materialized source data even in a failed startup.
        _emit(
            "LOCAL_INDEXING_SERVICE_STOPPED",
            code=code,
            error_type=type(error).__name__,
            **_failure_detail(error),
        )
        return 1
    finally:
        if runtime is not None:
            runtime.engine.dispose()
        if capture is not None:
            capture.close()


if __name__ == "__main__":
    raise SystemExit(main())
