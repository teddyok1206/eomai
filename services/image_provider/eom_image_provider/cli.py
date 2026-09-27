"""Small operator CLI for one isolated local-image invocation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eom_image_contracts import (
    LocalImageCompositeRequest,
    LocalImageGenerationRequest,
    LocalImageReferenceConditionedCompositeRequest,
    LocalImageReferenceConditionedCompositeRequestV2,
    validate_contract,
)

from eom_image_provider.diffusers_backend import Ssd1bDiffusersBackend
from eom_image_provider.model_manifest import create_model_manifest
from eom_image_provider.provider import (
    ProviderError,
    acquire_gpu_lease,
    generate_background,
    generate_composite_handoff,
    generate_reference_conditioned_composite_handoff,
    generate_reference_conditioned_composite_handoff_v2,
    load_json_object,
    reuse_composite_handoff,
    reuse_reference_conditioned_composite_handoff,
    reuse_reference_conditioned_composite_handoff_v2,
)
from eom_image_provider.reference_acquisition import (
    VisualReferenceAcquisitionError,
    load_acquisition_inputs,
    load_discovery_command,
    run_visual_reference_acquisition,
    run_visual_reference_discovery,
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
    conditioned = subparsers.add_parser("generate-reference-composite")
    conditioned.add_argument("--request", type=Path, required=True)
    conditioned.add_argument("--model-store-root", type=Path, required=True)
    conditioned.add_argument("--workspace", type=Path, required=True)
    conditioned.add_argument("--gpu-lock", type=Path, required=True)
    styled = subparsers.add_parser("generate-reference-style-composite")
    styled.add_argument("--request", type=Path, required=True)
    styled.add_argument("--model-store-root", type=Path, required=True)
    styled.add_argument("--style-adapter-store-root", type=Path, required=True)
    styled.add_argument("--workspace", type=Path, required=True)
    styled.add_argument("--gpu-lock", type=Path, required=True)
    reference = subparsers.add_parser("acquire-reference")
    reference.add_argument("--command", type=Path, required=True)
    reference.add_argument("--workspace", type=Path, required=True)
    discovery = subparsers.add_parser("discover-reference")
    discovery.add_argument("--command", type=Path, required=True)
    discovery.add_argument("--workspace", type=Path, required=True)
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
        elif args.operation == "generate-composite":
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
        elif args.operation == "generate-reference-composite":
            value = load_json_object(args.request, maximum_bytes=256 * 1024)
            validate_contract("reference-conditioned-composite-request", value)
            conditioned_request = LocalImageReferenceConditionedCompositeRequest.model_validate(
                value
            )
            conditioned_receipt = reuse_reference_conditioned_composite_handoff(
                workspace=args.workspace,
                request=conditioned_request,
            )
            if conditioned_receipt is None:
                with acquire_gpu_lease(args.gpu_lock):
                    conditioned_receipt = generate_reference_conditioned_composite_handoff(
                        model_store_root=args.model_store_root,
                        workspace=args.workspace,
                        request=conditioned_request,
                        backend=Ssd1bDiffusersBackend(),
                    )
            result = conditioned_receipt.model_dump(mode="json")
        elif args.operation == "generate-reference-style-composite":
            value = load_json_object(args.request, maximum_bytes=512 * 1024)
            validate_contract("reference-conditioned-composite-request-v2", value)
            styled_request = LocalImageReferenceConditionedCompositeRequestV2.model_validate(value)
            styled_receipt = reuse_reference_conditioned_composite_handoff_v2(
                workspace=args.workspace,
                request=styled_request,
            )
            if styled_receipt is None:
                with acquire_gpu_lease(args.gpu_lock):
                    styled_receipt = generate_reference_conditioned_composite_handoff_v2(
                        model_store_root=args.model_store_root,
                        style_adapter_store_root=args.style_adapter_store_root,
                        workspace=args.workspace,
                        request=styled_request,
                        backend=Ssd1bDiffusersBackend(),
                    )
            result = styled_receipt.model_dump(mode="json")
        elif args.operation == "acquire-reference":
            command, intent = load_acquisition_inputs(
                command_path=args.command,
                workspace=args.workspace,
            )
            acquisition = run_visual_reference_acquisition(
                command=command,
                intent=intent,
                workspace=args.workspace,
            )
            result = acquisition.result.model_dump(mode="json")
        else:
            discovery_command = load_discovery_command(
                command_path=args.command,
                workspace=args.workspace,
            )
            discovery = run_visual_reference_discovery(
                command=discovery_command,
                workspace=args.workspace,
            )
            result = discovery.result.model_dump(mode="json")
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, (ProviderError, VisualReferenceAcquisitionError))
            else "LOCAL_IMAGE_PROVIDER_FAILED"
        )
        print(code, file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
