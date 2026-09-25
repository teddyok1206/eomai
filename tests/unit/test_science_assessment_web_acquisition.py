from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import ScienceAssessmentWebCorpusPlan
from eom_catalog_service.science_assessment_web_acquisition import (
    ScienceAssessmentAcquisitionError,
    ScienceAssessmentWebAcquirer,
    _candidate_from_link,
    _original_filename,
    _validate_pdf,
)


def _plan() -> ScienceAssessmentWebCorpusPlan:
    value = json.loads(Path("config/science-assessment-web-corpus.v1.json").read_text())
    assert isinstance(value, dict)
    return ScienceAssessmentWebCorpusPlan.model_validate(value)


def test_candidate_classification_covers_kice_and_education_authority() -> None:
    kice = _candidate_from_link(
        post_url="https://legendstudy.com/1900",
        post_title="2026학년도 6월 모의평가 과학탐구",
        category_urls=("https://legendstudy.com/category/%ED%8F%89%EA%B0%80%EC%9B%90",),
        href="https://t1.daumcdn.net/file/2026_%EB%AC%BC%EB%A6%AC%ED%95%991_%EB%AC%B8%EC%A0%9C.pdf",
        link_text="2026학년도 6월 모의평가 물리학1 문제.pdf",
        allowed_hosts={"t1.daumcdn.net"},
    )
    assert kice is not None
    assert (
        kice.issuer_type,
        kice.administration_year,
        kice.grade,
        kice.subject_family,
        kice.session_label,
    ) == ("KICE", 2025, 3, "PHYSICS", "6월 모의평가")

    authority = _candidate_from_link(
        post_url="https://legendstudy.com/1901",
        post_title="2024년 9월 고2 전국연합학력평가",
        category_urls=("https://legendstudy.com/category/%EA%B3%A02",),
        href="https://blog.kakaocdn.net/file/2024_%ED%99%94%ED%95%99_%EB%AC%B8%EC%A0%9C.pdf",
        link_text="2024년 9월 고2 화학 문제.pdf",
        allowed_hosts={"blog.kakaocdn.net"},
    )
    assert authority is not None
    assert (
        authority.issuer_type,
        authority.administration_year,
        authority.grade,
        authority.subject_family,
        authority.session_label,
    ) == ("EDUCATION_AUTHORITY", 2024, 2, "CHEMISTRY", "9월 학력평가")


def test_candidate_rejects_answers_and_decodes_original_filename() -> None:
    rejected = _candidate_from_link(
        post_url="https://legendstudy.com/1902",
        post_title="2025년 3월 고1 전국연합학력평가",
        category_urls=("https://legendstudy.com/category/%EA%B3%A01",),
        href="https://t1.daumcdn.net/file/%ED%86%B5%ED%95%A9%EA%B3%BC%ED%95%99_%EC%A0%95%EB%8B%B5.pdf",
        link_text="통합과학 정답 및 해설.pdf",
        allowed_hosts={"t1.daumcdn.net"},
    )
    assert rejected is None
    assert (
        _original_filename(
            "",
            "https://t1.daumcdn.net/file/%ED%86%B5%ED%95%A9%EA%B3%BC%ED%95%99_%EB%AC%B8%EC%A0%9C.pdf",
        )
        == "통합과학_문제.pdf"
    )


def test_candidate_uses_decoded_category_for_issuer_classification() -> None:
    candidate = _candidate_from_link(
        post_url="https://legendstudy.com/1903",
        post_title="2012학년도 과학탐구",
        category_urls=(
            "https://legendstudy.com/category/%EA%B3%BC%ED%95%99%ED%83%90%EA%B5%AC%28%ED%8F%89%EA%B0%80%EC%9B%90%29",
        ),
        href="https://t1.daumcdn.net/file/biology-problem.pdf",
        link_text="2012학년도 생물1 문제.pdf",
        allowed_hosts={"t1.daumcdn.net"},
    )

    assert candidate is not None
    assert candidate.issuer_type == "KICE"
    assert candidate.administration_year == 2011
    assert candidate.grade == 3


class _DiscoveryHttp:
    def __init__(self, plan: ScienceAssessmentWebCorpusPlan) -> None:
        self.plan = plan
        self.requested: list[str] = []

    def read_html(self, url: str) -> str:
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return "User-agent: *\nDisallow: /admin\n"
        if "/category/" in url:
            if url.endswith("page=1"):
                return '<a href="/1900">one</a><a href="/1901">two</a>'
            return '<a href="/1900">one</a><a href="/1901">two</a>'
        if url.endswith("/1900"):
            return (
                "<title>2026학년도 6월 모의평가 과학탐구</title>"
                '<a href="https://t1.daumcdn.net/file/physics-problem.pdf">'
                "물리학1 문제.pdf</a>"
            )
        if url.endswith("/1901"):
            return (
                "<title>2024년 9월 고2 전국연합학력평가</title>"
                '<a href="https://blog.kakaocdn.net/file/chemistry-problem.pdf">'
                "화학 문제.pdf</a>"
            )
        raise AssertionError(url)


def test_discovery_deduplicates_posts_and_candidates_with_maps() -> None:
    plan = _plan()
    http = _DiscoveryHttp(plan)
    acquirer = ScienceAssessmentWebAcquirer(plan, http=cast(Any, http))

    result = acquirer.discover()

    assert result.post_count == 2
    assert len(result.candidates) == 2
    assert {value.subject_family for value in result.candidates} == {"CHEMISTRY", "PHYSICS"}
    assert sum(url.endswith("/1900") for url in http.requested) == 1
    assert sum(url.endswith("/1901") for url in http.requested) == 1


def test_pdf_validation_rejects_active_content_without_loading_full_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"x" * 1024 + b"/JavaScript" + b"x" * 1024)
    source.chmod(0o600)
    calls = iter(
        (
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            SimpleNamespace(returncode=0, stdout=b"Pages: 2\nEncrypted: no\n", stderr=b""),
        )
    )
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: next(calls))

    with pytest.raises(
        ScienceAssessmentAcquisitionError, match="SCIENCE_CORPUS_PDF_ACTIVE_CONTENT"
    ):
        _validate_pdf(source, qpdf=Path("/usr/bin/qpdf"), pdfinfo=Path("/usr/bin/pdfinfo"))
