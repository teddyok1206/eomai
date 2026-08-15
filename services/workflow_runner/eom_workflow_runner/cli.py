"""Long-running and one-shot workflow runner entry points."""

from __future__ import annotations

import argparse

from eom_orchestrator.database import build_engine

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.logging import configure_workflow_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-workflow-runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_once = subparsers.add_parser("run-once")
    run_once.add_argument("--workflow-id")
    subparsers.add_parser("serve")
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("workflow_id")
    args = parser.parse_args(argv)

    configure_workflow_logging()
    runner = WorkflowRunner(build_engine())
    if args.command == "run-once":
        return 0 if runner.run_once(args.workflow_id) is not None else 2
    if args.command == "serve":
        runner.serve()
        return 0
    if args.command == "reconcile":
        runner.reconcile(args.workflow_id)
        return 0
    return 1
