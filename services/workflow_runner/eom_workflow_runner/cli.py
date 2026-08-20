"""Long-running and one-shot workflow runner entry points."""

from __future__ import annotations

import argparse
import json

from eom_orchestrator.doctor import runtime_configuration_check
from eom_orchestrator.settings import Settings, SettingsError

from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.doctor import run_workflow_doctor
from eom_workflow_runner.logging import configure_workflow_logging
from eom_workflow_runner.readiness import WorkflowRuntimeNotReady


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-workflow-runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_once = subparsers.add_parser("run-once")
    run_once.add_argument("--workflow-id")
    subparsers.add_parser("serve")
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("workflow_id")
    subparsers.add_parser("doctor")
    args = parser.parse_args(argv)

    configure_workflow_logging()
    platform_settings: Settings | None = None
    if args.command == "doctor":
        try:
            platform_settings = Settings.from_environment()
        except SettingsError as exc:
            _print_configuration_not_ready(type(exc).__name__)
            return 1
        configuration = runtime_configuration_check(platform_settings)
        if not configuration.passed:
            _print_configuration_not_ready(configuration.detail)
            return 1
    runtime = (
        build_workflow_runtime(platform_settings=platform_settings)
        if platform_settings is not None
        else build_workflow_runtime()
    )
    try:
        if args.command == "run-once":
            try:
                result = runtime.runner.run_once(args.workflow_id)
            except WorkflowRuntimeNotReady as exc:
                _print_not_ready(exc)
                return 3
            return 0 if result is not None else 2
        if args.command == "serve":
            runtime.runner.serve()
            return 0
        if args.command == "reconcile":
            try:
                runtime.runner.reconcile(args.workflow_id)
            except WorkflowRuntimeNotReady as exc:
                _print_not_ready(exc)
                return 3
            return 0
        if args.command == "doctor":
            checks = run_workflow_doctor(
                runtime.workflow_settings,
                runtime.platform_settings,
                runtime.readiness,
                engine=runtime.engine,
            )
            passed = all(check.passed for check in checks)
            print(
                json.dumps(
                    {
                        "passed": passed,
                        "checks": [check.as_dict() for check in checks],
                    },
                    sort_keys=True,
                )
            )
            return 0 if passed else 1
        return 1
    finally:
        runtime.engine.dispose()


def _print_not_ready(exc: WorkflowRuntimeNotReady) -> None:
    print(
        json.dumps(
            {
                "ready": False,
                "error_code": "WORKFLOW_RUNTIME_NOT_READY",
                "failed_checks": list(exc.report.failed_codes),
            },
            sort_keys=True,
        )
    )


def _print_configuration_not_ready(detail: str) -> None:
    print(
        json.dumps(
            {
                "passed": False,
                "checks": [
                    {
                        "name": "orchestrator_runtime_configuration",
                        "status": "FAIL",
                        "code": "WORKER_CONFIGURATION_INVALID",
                        "detail": detail,
                        "passed": False,
                    }
                ],
            },
            sort_keys=True,
        )
    )
