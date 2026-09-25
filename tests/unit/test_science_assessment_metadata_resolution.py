from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    ScienceAssessmentAcquisitionSuccess,
    ScienceAssessmentAcquisitionSummary,
    ScienceAssessmentCorpusPdfValidator,
    ScienceAssessmentWebAcquisition,
    ScienceAssessmentWebCorpusPlan,
    validate_contract,
)
from eom_catalog_service.science_assessment_metadata_checkpoint import (
    load_science_assessment_metadata_resolution,
    write_science_assessment_metadata_resolution,
)
from eom_catalog_service.science_assessment_metadata_resolution import (
    ScienceAssessmentMetadataResolutionError,
    resolve_science_assessment_metadata,
)
from eom_identifiers import canonical_json_bytes, content_sha256


def _plan() -> ScienceAssessmentWebCorpusPlan:
    value = json.loads(Path("config/science-assessment-web-corpus.v1.json").read_text())
    assert isinstance(value, dict)
    return ScienceAssessmentWebCorpusPlan.model_validate(value)


def _success(
    *,
    post: str,
    text: str,
    family: str,
    label: str,
    issuer: str,
    year: int,
    grade: int,
    session: str,
    digest: str = "1",
) -> ScienceAssessmentAcquisitionSuccess:
    return ScienceAssessmentAcquisitionSuccess(
        post_url=f"https://legendstudy.com/{post}",
        download_url=f"https://t1.daumcdn.net/file/{post}.pdf",
        link_text=text,
        original_filename=f"{post}.pdf",
        subject_family=family,
        subject_label=label,
        issuer_type=issuer,
        administration_year=year,
        grade=grade,
        session_label=session,
        resolved_url=f"https://t1.daumcdn.net/file/{post}.pdf",
        member_path=f"documents/{digest * 64}.pdf",
        sha256="sha256:" + digest * 64,
        bytes=4096,
        page_count=4,
    )


def _acquisition(
    *observations: ScienceAssessmentAcquisitionSuccess,
) -> ScienceAssessmentWebAcquisition:
    plan = _plan()
    successful = tuple(
        sorted(
            observations,
            key=lambda value: (
                value.post_url,
                value.download_url,
                value.link_text,
                value.sha256,
            ),
        )
    )
    unique = {value.sha256: value.bytes for value in successful}
    value: dict[str, object] = {
        "schema_version": "science-assessment-web-acquisition/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "observed_at": "2026-09-25T16:35:28Z",
        "pdf_validator": ScienceAssessmentCorpusPdfValidator(
            qpdf_path="/usr/bin/qpdf",
            qpdf_sha256="sha256:" + "a" * 64,
            pdfinfo_path="/usr/bin/pdfinfo",
            pdfinfo_sha256="sha256:" + "b" * 64,
        ).model_dump(mode="json"),
        "successful_observations": [item.model_dump(mode="json") for item in successful],
        "failed_observations": [],
        "summary": ScienceAssessmentAcquisitionSummary(
            scanned_post_count=len(successful),
            candidate_count=len(successful),
            successful_observation_count=len(successful),
            failed_observation_count=0,
            rejected_link_count=0,
            unique_pdf_count=len(unique),
            unique_pdf_bytes=sum(unique.values()),
        ).model_dump(mode="json"),
        "acquisition_sha256": "sha256:" + "0" * 64,
    }
    value["acquisition_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "acquisition_sha256"}
    )
    return ScienceAssessmentWebAcquisition.model_validate(value)


def test_resolution_prefers_explicit_kice_alias_without_dropping_origins() -> None:
    acquisition = _acquisition(
        _success(
            post="100",
            text="2026학년도 6월 모의평가 물리학1 문제.pdf",
            family="PHYSICS",
            label="물리학1",
            issuer="KICE",
            year=2025,
            grade=3,
            session="6월 모의평가",
        ),
        _success(
            post="200",
            text="2025년 6월 고3 모의고사 물리1 문제.pdf",
            family="PHYSICS",
            label="물리1",
            issuer="EDUCATION_AUTHORITY",
            year=2025,
            grade=3,
            session="6월 학력평가",
        ),
    )

    resolution = resolve_science_assessment_metadata(acquisition)

    document = resolution.documents[0]
    assert document.issuer_type == "KICE"
    assert document.issuer_rule == "EXPLICIT_KICE"
    assert document.administration_year == 2025
    assert document.subject_label == "물리학1"
    assert document.session_label == "6월 모의평가"
    assert document.observation_count == 2
    assert document.had_metadata_conflict is True
    assert resolution.summary.successful_observation_count == 2
    validate_contract(
        "science-assessment-metadata-resolution",
        resolution.model_dump(mode="json"),
    )


def test_resolution_recognizes_combined_general_science_and_csats() -> None:
    combined = _acquisition(
        _success(
            post="100",
            text="2009년 3월 고1 모의고사 과학탐구 문제.pdf",
            family="GENERAL_SCIENCE",
            label="과학탐구",
            issuer="EDUCATION_AUTHORITY",
            year=2009,
            grade=1,
            session="3월 학력평가",
        ),
        _success(
            post="200",
            text="2009년 3월 고1 과탐(물리,화학,생명과학,지구과학) 문제.pdf",
            family="EARTH_SCIENCE",
            label="지구과학",
            issuer="EDUCATION_AUTHORITY",
            year=2009,
            grade=1,
            session="3월 학력평가",
        ),
    )
    csat = _acquisition(
        _success(
            post="300",
            text="2026학년도 11월 수능 화학1 문제.pdf",
            family="CHEMISTRY",
            label="화학1",
            issuer="KICE",
            year=2026,
            grade=3,
            session="11월 모의평가",
            digest="2",
        )
    )

    combined_document = resolve_science_assessment_metadata(combined).documents[0]
    csat_document = resolve_science_assessment_metadata(csat).documents[0]

    assert combined_document.subject_family == "GENERAL_SCIENCE"
    assert combined_document.subject_rule == "MULTI_SUBJECT_LIST"
    assert csat_document.administration_year == 2025
    assert csat_document.session_label == "대학수학능력시험"
    assert csat_document.session_rule == "EXPLICIT_KICE_CSAT"


def test_resolution_fails_closed_on_equal_rank_issuer_disagreement() -> None:
    acquisition = _acquisition(
        _success(
            post="100",
            text="2025년 6월 평가원 물리학1 문제.pdf",
            family="PHYSICS",
            label="물리학1",
            issuer="KICE",
            year=2025,
            grade=3,
            session="6월 모의평가",
        ),
        _success(
            post="200",
            text="2025년 6월 교육청 물리학1 문제.pdf",
            family="PHYSICS",
            label="물리학1",
            issuer="EDUCATION_AUTHORITY",
            year=2025,
            grade=3,
            session="6월 학력평가",
        ),
    )

    with pytest.raises(
        ScienceAssessmentMetadataResolutionError,
        match="METADATA_RESOLUTION_AMBIGUOUS",
    ):
        resolve_science_assessment_metadata(acquisition)


def test_resolution_checkpoint_is_exact_and_raw_acquisition_is_unchanged(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    acquisition = _acquisition(
        _success(
            post="100",
            text="2026학년도 6월 모의평가 생명과학1 문제.pdf",
            family="LIFE_SCIENCE",
            label="생명과학1",
            issuer="KICE",
            year=2025,
            grade=3,
            session="6월 모의평가",
        )
    )
    raw_before = canonical_json_bytes(acquisition.model_dump(mode="json"))
    resolution = resolve_science_assessment_metadata(acquisition)

    path = write_science_assessment_metadata_resolution(tmp_path, resolution)
    loaded = load_science_assessment_metadata_resolution(
        workspace=tmp_path,
        acquisition=acquisition,
    )

    assert loaded == resolution
    assert path.read_bytes() == canonical_json_bytes(resolution.model_dump(mode="json"))
    assert canonical_json_bytes(acquisition.model_dump(mode="json")) == raw_before

    value = json.loads(path.read_text())
    value["documents"][0]["session_label"] = "9월 모의평가"
    path.write_bytes(canonical_json_bytes(value))
    with pytest.raises(ValueError, match="resolution hash"):
        load_science_assessment_metadata_resolution(
            workspace=tmp_path,
            acquisition=acquisition,
        )
