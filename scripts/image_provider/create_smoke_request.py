#!/usr/bin/env python3
"""Create one protected, fixed-policy SSD-1B smoke request."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
from pathlib import Path

from eom_image_contracts import (
    LocalImageGenerationRequest,
    LocalImageModelManifest,
    content_sha256,
    text_sha256,
    validate_contract,
)
from eom_image_provider.provider import load_json_object

PROMPT = (
    "neutral educational science textbook background, subtle recycled paper texture, "
    "muted pale blue and warm gray, evenly lit, no objects, no text, no labels"
)
NEGATIVE_PROMPT = (
    "text, letters, numbers, labels, watermark, logo, face, person, graph, chart, equation, "
    "measurement, apparatus"
)


def _write(path: Path, payload: bytes) -> None:
    parent = path.parent
    metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SystemExit("LOCAL_IMAGE_SMOKE_PARENT_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_value = load_json_object(args.manifest, maximum_bytes=256 * 1024)
    validate_contract("model-manifest", manifest_value)
    manifest = LocalImageModelManifest.model_validate(manifest_value)
    body = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": "imgreq_" + secrets.token_hex(16),
        "idempotency_key": "local-image-smoke:" + secrets.token_hex(24),
        "model": {
            "model_id": manifest.model_id,
            "model_revision_id": manifest.model_revision_id,
            "manifest_sha256": manifest.manifest_sha256,
            "provider_family": manifest.provider_family,
            "runtime_contract_version": manifest.runtime_contract_version,
        },
        "prompt": PROMPT,
        "prompt_sha256": text_sha256(PROMPT),
        "negative_prompt": NEGATIVE_PROMPT,
        "negative_prompt_sha256": text_sha256(NEGATIVE_PROMPT),
        "seed": 20260901,
        "sampler": {
            "contract": "euler-discrete/ssd-1b-v1",
            "inference_steps": 20,
            "guidance_scale": 7.5,
            "dtype": "float16",
        },
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": "generated-background.png",
        "timeout_seconds": 600,
    }
    request = LocalImageGenerationRequest.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )
    value = request.model_dump(mode="json")
    validate_contract("generation-request", value)
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write(args.output, payload)
    print(f"REQUEST_ID={request.request_id}")
    print(f"REQUEST_SHA256={request.request_sha256}")
    print(f"MODEL_REVISION_ID={request.model.model_revision_id}")


if __name__ == "__main__":
    main()
