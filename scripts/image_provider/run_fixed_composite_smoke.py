#!/usr/bin/env python3
"""Run one disposable non-Item smoke through the fixed local-image unit."""

from __future__ import annotations

import json
import os
import pwd
import secrets
import shutil
import stat
import tempfile
from pathlib import Path

from eom_catalog_service.local_image_adapter import (
    FixedLocalImageProviderAdapter,
    load_local_image_provider_binding,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.vector_stimulus import (
    compose_vector_overlay_svg,
    rasterize_vector_svg,
    write_vector_svg,
)
from eom_identifiers import content_sha256
from eom_workflow.models import GeneratedVectorDrawingV5

STATE_ROOT = Path("/var/lib/eom-workflow-runner")


def _require_runner_identity() -> None:
    account = pwd.getpwnam("eom-workflow-runner")
    if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
        raise SystemExit("LOCAL_IMAGE_SMOKE_IDENTITY_INVALID")
    metadata = STATE_ROOT.lstat()
    if (
        STATE_ROOT.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != account.pw_uid
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SystemExit("LOCAL_IMAGE_SMOKE_STATE_ROOT_INVALID")


def _drawing() -> GeneratedVectorDrawingV5:
    return GeneratedVectorDrawingV5.model_validate(
        {
            "kind": "natural_scene",
            "production_route": "LOCAL_GENERATIVE_BACKGROUND",
            "background_style": "PAPER",
            "block_id": "block_image",
            "alt_text": "비권위 배경 위의 검증용 도형 A",
            "scene_description": "문자 없는 옅은 과학 교재 배경 위에 도형을 배치한다.",
            "scientific_constraints": ["검증용 원은 하나이다."],
            "required_labels": ["A"],
            "generation_prompt": "subtle pale blue and warm gray educational paper texture",
            "negative_prompt": "objects, people, instruments",
            "width_px": 800,
            "height_px": 500,
            "svg_overlay": (
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
                'viewBox="0 0 800 500"><circle cx="400" cy="250" fill="none" r="96" '
                'stroke="#111827" stroke-width="5"></circle><text fill="#111827" '
                'font-family="Droid Sans Fallback" font-size="28" x="390" y="260">'
                "A</text></svg>"
            ),
        }
    )


def main() -> None:
    _require_runner_identity()
    settings = CatalogSettings.from_environment()
    binding = load_local_image_provider_binding(settings.local_image_provider_binding)
    workflow_id = "workflow_" + secrets.token_hex(16)
    result_revision_id = "rev_" + secrets.token_hex(16)
    drawing = _drawing()
    drawing_hash = content_sha256(drawing.model_dump(mode="json"))
    state = Path(tempfile.mkdtemp(prefix="local-image-smoke.", dir=STATE_ROOT))
    state.chmod(0o700)
    output_directory = state / "output"
    output_directory.mkdir(mode=0o700)
    svg_path = state / "generated-stimulus.svg"
    overlay_path = state / "generated-overlay.png"
    succeeded = False
    workspace: Path | None = None
    try:
        write_vector_svg(svg_path, compose_vector_overlay_svg(drawing))
        rasterize_vector_svg(svg_path, overlay_path)
        materialized = FixedLocalImageProviderAdapter(settings).generate(
            workflow_id=workflow_id,
            result_revision_id=result_revision_id,
            drawing_hash=drawing_hash,
            drawing=drawing,
            overlay_path=overlay_path,
            binding=binding,
            output_directory=output_directory,
        )
        workspace = settings.local_image_workspace_root / materialized.request.generation.request_id
        print(
            json.dumps(
                {
                    "background_sha256": materialized.receipt.generation.output.sha256,
                    "binding_sha256": binding.binding_sha256,
                    "event": "LOCAL_IMAGE_FIXED_UNIT_SMOKE_PASS",
                    "final_sha256": materialized.receipt.output.sha256,
                    "model_revision_id": binding.model.model_revision_id,
                    "receipt_sha256": materialized.receipt.receipt_sha256,
                    "request_id": materialized.request.generation.request_id,
                    "unit_name": materialized.unit_name,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        succeeded = True
    finally:
        if succeeded:
            if workspace is not None:
                shutil.rmtree(workspace)
            shutil.rmtree(state)


if __name__ == "__main__":
    main()
