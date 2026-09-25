from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import ScienceAssessmentWebCorpusPlan
from eom_catalog_service.science_assessment_web_acquisition import (
    AcquiredScienceAssessmentPdf,
    ScienceAssessmentDiscovery,
    ScienceAssessmentPdfCandidate,
)
from eom_catalog_service.science_assessment_web_acquisition_checkpoint import (
    ScienceAssessmentAcquisitionCheckpointError,
    build_science_assessment_acquisition,
    load_science_assessment_acquisition,
    write_science_assessment_acquisition,
)
from eom_identifiers import sha256_file


def _plan() -> ScienceAssessmentWebCorpusPlan:
    value = json.loads(Path("config/science-assessment-web-corpus.v1.json").read_text())
    assert isinstance(value, dict)
    return ScienceAssessmentWebCorpusPlan.model_validate(value)


def _candidate() -> ScienceAssessmentPdfCandidate:
    return ScienceAssessmentPdfCandidate(
        post_url="https://legendstudy.com/1665",
        download_url="https://t1.daumcdn.net/file/physics.pdf",
        link_text="2026학년도 6월 모의평가 물리학1 문제.pdf",
        original_filename="physics.pdf",
        subject_family="PHYSICS",
        subject_label="물리학1",
        issuer_type="KICE",
        administration_year=2025,
        grade=3,
        session_label="6월 모의평가",
    )


def _workspace(tmp_path: Path) -> tuple[Path, AcquiredScienceAssessmentPdf]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    documents = workspace / "documents"
    documents.mkdir(mode=0o700)
    temporary = documents / "temporary.pdf"
    temporary.write_bytes(b"%PDF-1.7\n" + b"x" * 2048)
    content_hash = sha256_file(temporary)
    source = documents / f"{content_hash.removeprefix('sha256:')}.pdf"
    temporary.replace(source)
    source.chmod(0o600)
    return workspace, AcquiredScienceAssessmentPdf(
        candidate=_candidate(),
        resolved_url="https://t1.daumcdn.net/file/physics.pdf",
        source=source,
        sha256=content_hash,
        bytes=source.stat().st_size,
        page_count=4,
    )


def test_acquisition_checkpoint_round_trip_revalidates_local_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, acquired = _workspace(tmp_path)
    discovery = ScienceAssessmentDiscovery(
        post_count=1,
        candidates=(acquired.candidate,),
        rejected_link_count=2,
    )
    plan = _plan()
    checkpoint = build_science_assessment_acquisition(
        plan=plan,
        discovery=discovery,
        acquired=(acquired,),
        failures=(),
        observed_at=datetime(2026, 9, 25, 17, 0, tzinfo=UTC),
    )
    path = write_science_assessment_acquisition(workspace, checkpoint)
    monkeypatch.setattr(
        "eom_catalog_service.science_assessment_web_acquisition_checkpoint._validate_pdf",
        lambda *_args, **_kwargs: 4,
    )

    loaded = load_science_assessment_acquisition(
        plan=plan,
        workspace=workspace,
    )

    assert path.read_bytes().endswith(b"}")
    assert loaded.discovery.post_count == 1
    assert loaded.acquired == (acquired,)
    assert loaded.failures == ()
    assert loaded.acquisition == checkpoint


def test_acquisition_checkpoint_rejects_member_hash_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, acquired = _workspace(tmp_path)
    plan = _plan()
    checkpoint = build_science_assessment_acquisition(
        plan=plan,
        discovery=ScienceAssessmentDiscovery(
            post_count=1,
            candidates=(acquired.candidate,),
            rejected_link_count=0,
        ),
        acquired=(acquired,),
        failures=(),
    )
    write_science_assessment_acquisition(workspace, checkpoint)
    acquired.source.write_bytes(acquired.source.read_bytes() + b"drift")
    monkeypatch.setattr(
        "eom_catalog_service.science_assessment_web_acquisition_checkpoint._validate_pdf",
        lambda *_args, **_kwargs: 4,
    )

    with pytest.raises(
        ScienceAssessmentAcquisitionCheckpointError,
        match="ACQUISITION_MEMBER_INVALID",
    ):
        load_science_assessment_acquisition(plan=plan, workspace=workspace)


def test_acquisition_checkpoint_resolves_a_relative_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, acquired = _workspace(tmp_path)
    plan = _plan()
    checkpoint = build_science_assessment_acquisition(
        plan=plan,
        discovery=ScienceAssessmentDiscovery(
            post_count=1,
            candidates=(acquired.candidate,),
            rejected_link_count=0,
        ),
        acquired=(acquired,),
        failures=(),
    )
    write_science_assessment_acquisition(workspace, checkpoint)
    monkeypatch.setattr(
        "eom_catalog_service.science_assessment_web_acquisition_checkpoint._validate_pdf",
        lambda *_args, **_kwargs: 4,
    )
    monkeypatch.chdir(tmp_path)

    loaded = load_science_assessment_acquisition(
        plan=plan,
        workspace=Path("workspace"),
    )

    assert loaded.acquired[0].source == acquired.source
