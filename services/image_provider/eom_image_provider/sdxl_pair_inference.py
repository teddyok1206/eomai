"""One numerical lifecycle shared by separately admitted matched comparison contracts."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts.models import LocalImageRuntime
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonBudget,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import (
    LocalImageSdxlLineartProbeCommand,
    SdxlLineartProbeCase,
    SdxlProbeErrorCode,
)

from eom_image_provider.provider import ProviderError, acquire_gpu_lease
from eom_image_provider.sdxl_lineart_probe import MAX_PNG_BYTES, SdxlProbeBackend, sdxl_publication
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def create_sdxl_pair_directories(root: int, workspace: Path) -> None:
    create_staged_directory(root, "outputs")
    with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as out:
        for arm in LEARNED_COMPARISON_ARMS:
            create_staged_directory(out, arm.lower())
            with verified_directory(
                workspace / "outputs" / arm.lower(), expected_owner_uid=os.geteuid()
            ) as arm_root:
                for name in ("raw", "final"):
                    create_staged_directory(arm_root, name)


@dataclass(frozen=True, slots=True)
class SdxlPairInferenceEvidence:
    outputs: tuple[SdxlLearnedComparisonOutput, ...]
    runtime: LocalImageRuntime | None
    error_code: SdxlProbeErrorCode | None


def run_sdxl_pair_inference(
    *,
    root: int,
    stack: ResolvedSdxlStack,
    material: SdxlLoraAdapterMaterial,
    baseline: LocalImageSdxlLineartProbeCommand,
    cases: tuple[SdxlLineartProbeCase, ...],
    inputs: Mapping[str, bytes],
    conditioning_hashes: Mapping[str, str],
    seed: int,
    budget: SdxlLearnedComparisonBudget,
    start: float,
    gpu_lock: Path,
    backend: SdxlProbeBackend,
) -> SdxlPairInferenceEvidence:
    produced: list[SdxlLearnedComparisonOutput] = []
    runtime: LocalImageRuntime | None = None
    error: SdxlProbeErrorCode | None = None
    try:
        with acquire_gpu_lease(gpu_lock):
            for arm in LEARNED_COMPARISON_ARMS:
                if (time.monotonic() - start) * 1000 >= budget.maximum_duration_ms:
                    raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                # A new pipeline avoids contaminating BASE with a previously loaded LoRA.
                with backend.open(
                    stack, style_adapter=material if arm == "LORA" else None
                ) as session:
                    for case in cases:
                        if (time.monotonic() - start) * 1000 >= budget.maximum_duration_ms:
                            raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                        call_start = time.monotonic()
                        generated = session.generate(
                            conditioning=inputs[case.case_id],
                            prompt=case.prompt_en,
                            negative_prompt=case.negative_prompt_en,
                            seed=seed,
                            command=baseline,
                        )
                        current = LocalImageRuntime.model_validate_json(
                            generated.runtime.model_dump_json()
                        )
                        if (
                            runtime is None
                            or current.peak_gpu_memory_bytes > runtime.peak_gpu_memory_bytes
                        ):
                            runtime = current
                        if not 0 < len(generated.png_bytes) <= MAX_PNG_BYTES:
                            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
                        if (
                            current.peak_gpu_memory_bytes > budget.maximum_peak_gpu_memory_bytes
                            or (time.monotonic() - start) * 1000 > budget.maximum_duration_ms
                        ):
                            raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                        final = sdxl_publication(generated.png_bytes)
                        filename = f"{case.case_id}-{seed:010d}.png"
                        output = SdxlLearnedComparisonOutput(
                            arm=arm,
                            case_id=case.case_id,
                            seed=seed,
                            reference_sha256=case.reference_image.sha256,
                            conditioning_sha256=conditioning_hashes[case.case_id],
                            member_path=f"outputs/{arm.lower()}/final/{filename}",
                            sha256=_sha(final),
                            size_bytes=len(final),
                            raw_member_path=f"outputs/{arm.lower()}/raw/{filename}",
                            raw_sha256=_sha(generated.png_bytes),
                            raw_size_bytes=len(generated.png_bytes),
                            width_px=800,
                            height_px=500,
                            duration_ms=max(1, int((time.monotonic() - call_start) * 1000)),
                            peak_gpu_memory_bytes=current.peak_gpu_memory_bytes,
                        )
                        write_staged_member(root, output.raw_member_path, generated.png_bytes)
                        write_staged_member(root, output.member_path, final)
                        produced.append(output)
    except ProviderError as exc:
        error = (
            cast(SdxlProbeErrorCode, exc.code) if exc.code in _ERRORS else "SDXL_PROBE_EXEC_FAILED"
        )
    except Exception:
        error = "SDXL_PROBE_EXEC_FAILED"
    if error is None and (time.monotonic() - start) * 1000 > budget.maximum_duration_ms:
        error = "SDXL_PROBE_BUDGET_EXCEEDED"
    return SdxlPairInferenceEvidence(tuple(produced), runtime, error)
