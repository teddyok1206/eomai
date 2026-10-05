#!/usr/bin/env python3
"""Operator presentation adapter for the pinned native SDXL training application."""

from __future__ import annotations

import argparse
import json
import os
import pwd
from pathlib import Path

from eom_image_contracts import ImageEvaluationArtifactMember, content_json_bytes, validate_contract
from eom_image_contracts.sdxl_native_lora import (
    native_lora_command_protocol,
)
from eom_image_contracts.sdxl_native_lora_sources import NATIVE_LORA_MAX_METADATA_BYTES
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.database import build_engine
from eom_orchestrator.sdxl_native_lora_inputs import (
    prepare_sdxl_native_lora_inputs,
    resolve_sdxl_native_lora_sources,
)
from eom_orchestrator.sdxl_probe_workspace import (
    SdxlProbeWorkspaceOwner,
    dispatch_sdxl_native_lora,
    stage_sdxl_native_lora_inputs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-revision-id", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--schema-version", choices=("1.0", "1.1"), default="1.0")
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--preflight-only", action="store_true")
    execution.add_argument("--dispatch", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("SDXL_NATIVE_LORA_OPERATOR_IDENTITY_INVALID")
    pointer = ImageEvaluationArtifactMember(
        artifact_id=args.artifact_id,
        artifact_revision_id=args.artifact_revision_id,
        member_path="manifests/sdxl-native-lora-command.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-sdxl-native-lora-command/"
            + args.schema_version
        ),
        media_type="application/json",
        sha256=args.sha256,
    )
    engine = build_engine()
    try:
        raw = resolve_control_artifact_member(
            engine, pointer, maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES
        )
        value = json.loads(raw)
        protocol = native_lora_command_protocol(
            "local-image-sdxl-native-lora-command/" + args.schema_version
        )
        validate_contract(protocol.contract, value)
        command = protocol.model.model_validate(value)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise SystemExit("SDXL_NATIVE_LORA_COMMAND_CANONICAL_INVALID")
        if args.preflight_only:
            admitted = resolve_sdxl_native_lora_sources(engine, command)
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_METADATA_PASS",
                        "run_id": command.training_run_id,
                        "samples": len(admitted.sources.targets),
                        "target_png_reads": 0,
                        "gpu_calls": 0,
                    },
                    sort_keys=True,
                )
            )
            return
        prepared = prepare_sdxl_native_lora_inputs(engine, command)
        account = pwd.getpwnam("eom-image")
        staged = stage_sdxl_native_lora_inputs(
            prepared,
            workspace_parent=Path("/srv/eom/image-training-workspaces"),
            worker=SdxlProbeWorkspaceOwner(account.pw_uid, account.pw_gid),
        )
        if args.dispatch:
            dispatch_sdxl_native_lora(staged)
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
