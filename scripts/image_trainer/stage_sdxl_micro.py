#!/usr/bin/env python3
"""Operator presentation adapter for one pinned Orchestrator SDXL micro handoff."""

from __future__ import annotations

import argparse
import json
import os
import pwd
from pathlib import Path

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageSdxlLoraMicroCommand,
    content_json_bytes,
    validate_contract,
)
from eom_image_contracts.sdxl_reviewed_micro import LocalImageSdxlReviewedMicroCommand
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.database import build_engine
from eom_orchestrator.sdxl_micro_inputs import prepare_sdxl_micro_inputs
from eom_orchestrator.sdxl_probe_workspace import (
    SdxlProbeWorkspaceOwner,
    dispatch_sdxl_micro_probe,
    stage_sdxl_micro_inputs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-revision-id", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--schema-version", choices=("1.0", "1.1"), default="1.0")
    args = parser.parse_args()
    if os.geteuid() != 0 or (args.preflight_only and args.dispatch):
        raise SystemExit("SDXL_MICRO_OPERATOR_ARGUMENTS_INVALID")
    pointer = ImageEvaluationArtifactMember(
        artifact_id=args.artifact_id,
        artifact_revision_id=args.artifact_revision_id,
        member_path="manifests/sdxl-lora-micro-command.json",
        schema_ref="eom://schemas/image-provider/local-image-sdxl-lora-micro-command/"
        + args.schema_version,
        media_type="application/json",
        sha256=args.sha256,
    )
    engine = build_engine()
    try:
        raw = resolve_control_artifact_member(engine, pointer, maximum_bytes=128 * 1024)
        value = json.loads(raw)
        command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand
        if args.schema_version == "1.1":
            validate_contract("sdxl-lora-micro-command-v2", value)
            command = LocalImageSdxlReviewedMicroCommand.model_validate(value)
        else:
            validate_contract("sdxl-lora-micro-command", value)
            command = LocalImageSdxlLoraMicroCommand.model_validate(value)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise SystemExit("SDXL_MICRO_COMMAND_CANONICAL_INVALID")
        prepared = prepare_sdxl_micro_inputs(engine, command)
        if args.preflight_only:
            print(json.dumps({"status": "PREFLIGHT_PASS", "run_id": command.training_run_id}))
            return
        account = pwd.getpwnam("eom-image")
        staged = stage_sdxl_micro_inputs(
            prepared,
            workspace_parent=Path("/srv/eom/image-training-workspaces"),
            worker=SdxlProbeWorkspaceOwner(account.pw_uid, account.pw_gid),
        )
        if args.dispatch:
            dispatch_sdxl_micro_probe(staged)
        print(
            json.dumps(
                {
                    "status": "DISPATCHED" if args.dispatch else "STAGED",
                    "workspace": str(staged.workspace),
                    "systemd_unit": staged.systemd_unit,
                    "command_sha256": staged.command_sha256,
                },
                sort_keys=True,
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
