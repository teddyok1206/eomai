"""Read-only admission of original TRAIN cases and a separately pinned learned extractor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from eom_image_contracts import (
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartManifest,
    LocalImageSdxlLineartProbeCommand,
    content_json_bytes,
    select_informative_lineart_cases,
    validate_contract,
    validate_informative_lineart_pointer,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember, resolve_sdxl_probe_sources


@dataclass(frozen=True, slots=True)
class PreparedInformativeLineartExtractionInputs:
    command: LocalImageInformativeLineartExtractionCommand
    baseline: LocalImageSdxlLineartProbeCommand
    manifest: LocalImageInformativeLineartManifest
    files: tuple[SdxlProbeInputMember, ...]


def prepare_informative_lineart_extraction_inputs(
    engine: Engine,
    command: LocalImageInformativeLineartExtractionCommand,
) -> PreparedInformativeLineartExtractionInputs:
    """Admit all original lineage before materializing PNGs; never register/dispatch or write DB."""
    try:
        value = command.model_dump(mode="json")
        validate_contract("informative-lineart-extraction-command", value)
        command = LocalImageInformativeLineartExtractionCommand.model_validate(value)
        baseline_raw = resolve_control_artifact_member(
            engine, command.baseline_command, maximum_bytes=128 * 1024
        )
        baseline_value = json.loads(baseline_raw)
        validate_contract("sdxl-lineart-probe-command", baseline_value)
        baseline = LocalImageSdxlLineartProbeCommand.model_validate(baseline_value)
        if baseline_raw != content_json_bytes(baseline.model_dump(mode="json")):
            raise ValueError("noncanonical original command")
        manifest_raw = resolve_control_artifact_member(
            engine, command.extractor_manifest, maximum_bytes=64 * 1024
        )
        manifest_value = json.loads(manifest_raw)
        validate_contract("informative-lineart-manifest", manifest_value)
        manifest = LocalImageInformativeLineartManifest.model_validate(manifest_value)
        if manifest_raw != content_json_bytes(manifest.model_dump(mode="json")):
            raise ValueError("noncanonical extractor manifest")
        validate_informative_lineart_pointer(command.extractor, manifest)
        cases = select_informative_lineart_cases(command, baseline)
        # Reuse the complete existing approval, crop, pilot, Graph/source and TRAIN admission.
        sources = resolve_sdxl_probe_sources(engine, baseline)
        selected = {case.case_id: member for case, member in sources.selected}
        reads = tuple(
            BoundedControlArtifactRead(case.reference_image, selected[case.case_id].size_bytes)
            for case in cases
        )
        payloads = resolve_control_artifact_members(engine, reads)
        files = [
            SdxlProbeInputMember(case.staged_member_path, case.reference_image.sha256, payload)
            for case, payload in zip(cases, payloads, strict=True)
        ]
        for name, payload in (
            ("command.json", content_json_bytes(value)),
            ("inputs/baseline-command.json", baseline_raw),
            ("inputs/extractor-manifest.json", manifest_raw),
        ):
            files.append(
                SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(payload).hexdigest(), payload)
            )
        return PreparedInformativeLineartExtractionInputs(
            command, baseline, manifest, tuple(sorted(files, key=lambda file: file.member_path))
        )
    except (ValueError, TypeError, KeyError, JsonSchemaValidationError) as exc:
        raise ValueError("LINEART_EXTRACTION_SOURCE_INVALID") from exc
