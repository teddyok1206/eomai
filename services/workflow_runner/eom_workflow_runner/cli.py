"""Long-running and one-shot workflow runner entry points."""

from __future__ import annotations

import argparse

from eom_workflow_runner.composition import build_workflow_runtime
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
    runtime = build_workflow_runtime()
    try:
        if args.command == "run-once":
            return 0 if runtime.runner.run_once(args.workflow_id) is not None else 2
        if args.command == "serve":
            runtime.runner.serve()
            return 0
        if args.command == "reconcile":
            runtime.runner.reconcile(args.workflow_id)
            return 0
        return 1
    finally:
        runtime.engine.dispose()
