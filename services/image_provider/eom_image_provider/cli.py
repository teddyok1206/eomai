"""Small operator CLI for one isolated local-image invocation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eom_image_contracts import (
    LocalImageCompositeRequest,
    LocalImageGenerationRequest,
    validate_contract,
)

from eom_image_provider.diffusers_backend import Ssd1bDiffusersBackend
from eom_image_provider.model_manifest import create_model_manifest
from eom_image_provider.provider import (
    ProviderError,
    acquire_gpu_lease,
    generate_background,
    generate_composite_handoff,
    load_json_object,
    reuse_composite_handoff,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eom-local-image")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--request", type=Path, required=True)
    generate.add_argument("--model-store-root", type=Path, required=True)
    generate.add_argument("--workspace", type=Path, required=True)
    composite = subparsers.add_parser("generate-composite")
    composite.add_argument("--request", type=Path, required=True)
    composite.add_argument("--model-store-root", type=Path, required=True)
    composite.add_argument("--workspace", type=Path, required=True)
    composite.add_argument("--gpu-lock", type=Path, required=True)
    manifest = subparsers.add_parser("create-manifest")
    manifest.add_argument("--revision-directory", type=Path, required=True)
    manifest.add_argument("--model-id", required=True)
    manifest.add_argument("--model-revision-id", required=True)
    manifest.add_argument("--approved-by", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.operation == "create-manifest":
            manifest = create_model_manifest(
                args.revision_directory,
                model_id=args.model_id,
                model_revision_id=args.model_revision_id,
                approved_by=args.approved_by,
            )
            result = manifest.model_dump(mode="json")
        elif args.operation == "generate":
            value = load_json_object(args.request, maximum_bytes=64 * 1024)
            validate_contract("generation-request", value)
            generation_request = LocalImageGenerationRequest.model_validate(value)
            generation_receipt = generate_background(
                model_store_root=args.model_store_root,
                workspace=args.workspace,
                request=generation_request,
                backend=Ssd1bDiffusersBackend(),
            )
            result = generation_receipt.model_dump(mode="json")
        else:
            value = load_json_object(args.request, maximum_bytes=128 * 1024)
            validate_contract("composite-request", value)
            composite_request = LocalImageCompositeRequest.model_validate(value)
            composite_receipt = reuse_composite_handoff(
                workspace=args.workspace,
                request=composite_request,
            )
            if composite_receipt is None:
                with acquire_gpu_lease(args.gpu_lock):
                    composite_receipt = generate_composite_handoff(
                        model_store_root=args.model_store_root,
                        workspace=args.workspace,
                        request=composite_request,
                        backend=Ssd1bDiffusersBackend(),
                    )
            result = composite_receipt.model_dump(mode="json")
    except Exception as exc:
        code = exc.code if isinstance(exc, ProviderError) else "LOCAL_IMAGE_PROVIDER_FAILED"
        print(code, file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
