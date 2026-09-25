"""Immutable local checkpoint for science-assessment publication metadata."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from eom_catalog_contracts import (
    ScienceAssessmentMetadataResolution,
    ScienceAssessmentWebAcquisition,
    validate_contract,
    validate_science_metadata_resolution_against_acquisition,
)
from eom_identifiers import canonical_json_bytes

from eom_catalog_service.science_assessment_metadata_resolution import (
    resolve_science_assessment_metadata,
)

METADATA_RESOLUTION_NAME = "metadata-resolution.json"
MAX_METADATA_RESOLUTION_BYTES = 16 * 1024 * 1024


class ScienceAssessmentMetadataCheckpointError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def write_science_assessment_metadata_resolution(
    workspace: Path,
    resolution: ScienceAssessmentMetadataResolution,
) -> Path:
    _require_workspace(workspace)
    path = workspace / METADATA_RESOLUTION_NAME
    payload = canonical_json_bytes(resolution.model_dump(mode="json"))
    if len(payload) > MAX_METADATA_RESOLUTION_BYTES:
        raise ScienceAssessmentMetadataCheckpointError(
            "SCIENCE_CORPUS_METADATA_RESOLUTION_TOO_LARGE"
        )
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short metadata resolution write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def load_science_assessment_metadata_resolution(
    *,
    workspace: Path,
    acquisition: ScienceAssessmentWebAcquisition,
) -> ScienceAssessmentMetadataResolution:
    _require_workspace(workspace)
    path = workspace / METADATA_RESOLUTION_NAME
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= MAX_METADATA_RESOLUTION_BYTES
    ):
        raise ScienceAssessmentMetadataCheckpointError("SCIENCE_CORPUS_METADATA_RESOLUTION_INVALID")
    raw = path.read_bytes()
    value: object = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ScienceAssessmentMetadataCheckpointError("SCIENCE_CORPUS_METADATA_RESOLUTION_INVALID")
    validate_contract("science-assessment-metadata-resolution", value)
    resolution = ScienceAssessmentMetadataResolution.model_validate(value)
    validate_science_metadata_resolution_against_acquisition(resolution, acquisition)
    if resolution != resolve_science_assessment_metadata(acquisition):
        raise ScienceAssessmentMetadataCheckpointError(
            "SCIENCE_CORPUS_METADATA_RESOLUTION_MISMATCH"
        )
    return resolution


def _require_workspace(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) not in {0o700, 0o750}
    ):
        raise ScienceAssessmentMetadataCheckpointError("SCIENCE_CORPUS_WORKSPACE_INVALID")
