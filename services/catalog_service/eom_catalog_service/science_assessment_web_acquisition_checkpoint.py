"""Typed local handoff between untrusted web acquisition and Catalog publication."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from eom_catalog_contracts import (
    ScienceAssessmentAcquisitionFailureObservation,
    ScienceAssessmentAcquisitionSuccess,
    ScienceAssessmentAcquisitionSummary,
    ScienceAssessmentCorpusPdfValidator,
    ScienceAssessmentWebAcquisition,
    ScienceAssessmentWebCorpusPlan,
    validate_contract,
    validate_science_acquisition_against_plan,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file

from eom_catalog_service.science_assessment_web_acquisition import (
    AcquiredScienceAssessmentPdf,
    ScienceAssessmentAcquisitionFailure,
    ScienceAssessmentDiscovery,
    ScienceAssessmentPdfCandidate,
    _validate_pdf,
)

MAX_ACQUISITION_MANIFEST_BYTES = 32 * 1024 * 1024
ACQUISITION_MANIFEST_NAME = "acquisition-manifest.json"


class ScienceAssessmentAcquisitionCheckpointError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ValidatedScienceAssessmentAcquisition:
    acquisition: ScienceAssessmentWebAcquisition
    discovery: ScienceAssessmentDiscovery
    acquired: tuple[AcquiredScienceAssessmentPdf, ...]
    failures: tuple[ScienceAssessmentAcquisitionFailure, ...]


def build_science_assessment_acquisition(
    *,
    plan: ScienceAssessmentWebCorpusPlan,
    discovery: ScienceAssessmentDiscovery,
    acquired: tuple[AcquiredScienceAssessmentPdf, ...],
    failures: tuple[ScienceAssessmentAcquisitionFailure, ...],
    observed_at: datetime | None = None,
) -> ScienceAssessmentWebAcquisition:
    if not acquired:
        raise ScienceAssessmentAcquisitionCheckpointError("SCIENCE_CORPUS_NO_VALID_PDFS")
    successful = tuple(
        sorted(
            (
                ScienceAssessmentAcquisitionSuccess(
                    post_url=value.candidate.post_url,
                    download_url=value.candidate.download_url,
                    link_text=value.candidate.link_text,
                    original_filename=value.candidate.original_filename,
                    subject_family=value.candidate.subject_family,
                    subject_label=value.candidate.subject_label,
                    issuer_type=value.candidate.issuer_type,
                    administration_year=value.candidate.administration_year,
                    grade=value.candidate.grade,
                    session_label=value.candidate.session_label,
                    resolved_url=value.resolved_url,
                    member_path=(f"documents/{value.sha256.removeprefix('sha256:')}.pdf"),
                    sha256=value.sha256,
                    bytes=value.bytes,
                    page_count=value.page_count,
                )
                for value in acquired
            ),
            key=lambda value: (
                value.post_url,
                value.download_url,
                value.link_text,
                value.sha256,
            ),
        )
    )
    failed = tuple(
        sorted(
            (
                ScienceAssessmentAcquisitionFailureObservation(
                    post_url=value.candidate.post_url,
                    download_url=value.candidate.download_url,
                    link_text=value.candidate.link_text,
                    original_filename=value.candidate.original_filename,
                    subject_family=value.candidate.subject_family,
                    subject_label=value.candidate.subject_label,
                    issuer_type=value.candidate.issuer_type,
                    administration_year=value.candidate.administration_year,
                    grade=value.candidate.grade,
                    session_label=value.candidate.session_label,
                    error_code=value.error_code,
                )
                for value in failures
            ),
            key=lambda value: (
                value.post_url,
                value.download_url,
                value.link_text,
                value.error_code,
            ),
        )
    )
    unique_sizes: dict[str, int] = {}
    for observation in successful:
        prior = unique_sizes.setdefault(observation.sha256, observation.bytes)
        if prior != observation.bytes:
            raise ScienceAssessmentAcquisitionCheckpointError(
                "SCIENCE_CORPUS_CONTENT_METADATA_CONFLICT"
            )
    validator = ScienceAssessmentCorpusPdfValidator(
        qpdf_path="/usr/bin/qpdf",
        qpdf_sha256=sha256_file(Path("/usr/bin/qpdf")),
        pdfinfo_path="/usr/bin/pdfinfo",
        pdfinfo_sha256=sha256_file(Path("/usr/bin/pdfinfo")),
    )
    summary = ScienceAssessmentAcquisitionSummary(
        scanned_post_count=discovery.post_count,
        candidate_count=len(discovery.candidates),
        successful_observation_count=len(successful),
        failed_observation_count=len(failed),
        rejected_link_count=discovery.rejected_link_count,
        unique_pdf_count=len(unique_sizes),
        unique_pdf_bytes=sum(unique_sizes.values()),
    )
    value: dict[str, object] = {
        "schema_version": "science-assessment-web-acquisition/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "observed_at": (observed_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
        "pdf_validator": validator.model_dump(mode="json"),
        "successful_observations": [item.model_dump(mode="json") for item in successful],
        "failed_observations": [item.model_dump(mode="json") for item in failed],
        "summary": summary.model_dump(mode="json"),
        "acquisition_sha256": "sha256:" + "0" * 64,
    }
    value["acquisition_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "acquisition_sha256"}
    )
    acquisition = ScienceAssessmentWebAcquisition.model_validate(value)
    validate_science_acquisition_against_plan(acquisition, plan)
    validate_contract("science-assessment-web-acquisition", acquisition.model_dump(mode="json"))
    return acquisition


def write_science_assessment_acquisition(
    workspace: Path,
    acquisition: ScienceAssessmentWebAcquisition,
) -> Path:
    _require_workspace(workspace)
    path = workspace / ACQUISITION_MANIFEST_NAME
    payload = canonical_json_bytes(acquisition.model_dump(mode="json"))
    if len(payload) > MAX_ACQUISITION_MANIFEST_BYTES:
        raise ScienceAssessmentAcquisitionCheckpointError(
            "SCIENCE_CORPUS_ACQUISITION_MANIFEST_TOO_LARGE"
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
                raise OSError("short acquisition manifest write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def load_science_assessment_acquisition(
    *,
    plan: ScienceAssessmentWebCorpusPlan,
    workspace: Path,
) -> ValidatedScienceAssessmentAcquisition:
    _require_workspace(workspace)
    path = workspace / ACQUISITION_MANIFEST_NAME
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= MAX_ACQUISITION_MANIFEST_BYTES
    ):
        raise ScienceAssessmentAcquisitionCheckpointError(
            "SCIENCE_CORPUS_ACQUISITION_MANIFEST_INVALID"
        )
    raw = path.read_bytes()
    value: object = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ScienceAssessmentAcquisitionCheckpointError(
            "SCIENCE_CORPUS_ACQUISITION_MANIFEST_INVALID"
        )
    validate_contract("science-assessment-web-acquisition", value)
    acquisition = ScienceAssessmentWebAcquisition.model_validate(value)
    validate_science_acquisition_against_plan(acquisition, plan)
    if (
        sha256_file(Path(acquisition.pdf_validator.qpdf_path))
        != acquisition.pdf_validator.qpdf_sha256
        or sha256_file(Path(acquisition.pdf_validator.pdfinfo_path))
        != acquisition.pdf_validator.pdfinfo_sha256
    ):
        raise ScienceAssessmentAcquisitionCheckpointError("SCIENCE_CORPUS_PDF_VALIDATOR_DRIFT")
    checked: dict[str, Path] = {}
    acquired: list[AcquiredScienceAssessmentPdf] = []
    for observation in acquisition.successful_observations:
        source = _resolve_member(workspace, observation.member_path)
        prior = checked.get(observation.sha256)
        if prior is None:
            metadata = source.lstat()
            if (
                metadata.st_size != observation.bytes
                or sha256_file(source) != observation.sha256
                or _validate_pdf(
                    source,
                    qpdf=Path(acquisition.pdf_validator.qpdf_path),
                    pdfinfo=Path(acquisition.pdf_validator.pdfinfo_path),
                )
                != observation.page_count
            ):
                raise ScienceAssessmentAcquisitionCheckpointError(
                    "SCIENCE_CORPUS_ACQUISITION_MEMBER_INVALID"
                )
            checked[observation.sha256] = source
        elif source != prior:
            raise ScienceAssessmentAcquisitionCheckpointError(
                "SCIENCE_CORPUS_ACQUISITION_MEMBER_DUPLICATED"
            )
        acquired.append(
            AcquiredScienceAssessmentPdf(
                candidate=_candidate_from_success(observation),
                resolved_url=observation.resolved_url,
                source=source,
                sha256=observation.sha256,
                bytes=observation.bytes,
                page_count=observation.page_count,
            )
        )
    failures = tuple(
        ScienceAssessmentAcquisitionFailure(
            candidate=_candidate_from_failure(observation),
            error_code=observation.error_code,
        )
        for observation in acquisition.failed_observations
    )
    candidates = tuple(value.candidate for value in acquired) + tuple(
        value.candidate for value in failures
    )
    discovery = ScienceAssessmentDiscovery(
        post_count=acquisition.summary.scanned_post_count,
        candidates=tuple(
            sorted(
                candidates, key=lambda value: (value.download_url, value.post_url, value.link_text)
            )
        ),
        rejected_link_count=acquisition.summary.rejected_link_count,
    )
    return ValidatedScienceAssessmentAcquisition(
        acquisition=acquisition,
        discovery=discovery,
        acquired=tuple(acquired),
        failures=failures,
    )


def _candidate_from_success(
    value: ScienceAssessmentAcquisitionSuccess,
) -> ScienceAssessmentPdfCandidate:
    return ScienceAssessmentPdfCandidate(
        post_url=value.post_url,
        download_url=value.download_url,
        link_text=value.link_text,
        original_filename=value.original_filename,
        subject_family=value.subject_family,
        subject_label=value.subject_label,
        issuer_type=value.issuer_type,
        administration_year=value.administration_year,
        grade=value.grade,
        session_label=value.session_label,
    )


def _candidate_from_failure(
    value: ScienceAssessmentAcquisitionFailureObservation,
) -> ScienceAssessmentPdfCandidate:
    return ScienceAssessmentPdfCandidate(
        post_url=value.post_url,
        download_url=value.download_url,
        link_text=value.link_text,
        original_filename=value.original_filename,
        subject_family=value.subject_family,
        subject_label=value.subject_label,
        issuer_type=value.issuer_type,
        administration_year=value.administration_year,
        grade=value.grade,
        session_label=value.session_label,
    )


def _require_workspace(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) not in {0o700, 0o750}
    ):
        raise ScienceAssessmentAcquisitionCheckpointError("SCIENCE_CORPUS_WORKSPACE_INVALID")


def _resolve_member(workspace: Path, member_path: str) -> Path:
    relative = PurePosixPath(member_path)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
        raise ScienceAssessmentAcquisitionCheckpointError(
            "SCIENCE_CORPUS_ACQUISITION_MEMBER_INVALID"
        )
    root = workspace.resolve(strict=True)
    source = root / Path(*relative.parts)
    resolved = source.resolve(strict=True)
    metadata = resolved.lstat()
    if (
        resolved != source
        or not resolved.is_relative_to(root)
        or source.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise ScienceAssessmentAcquisitionCheckpointError(
            "SCIENCE_CORPUS_ACQUISITION_MEMBER_INVALID"
        )
    return resolved
