from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    ScienceAssessmentCorpusIntakeShard,
    ScienceAssessmentCorpusSourcePointer,
    ScienceAssessmentWebCorpusPlan,
    validate_contract,
    validate_science_corpus_manifest_against_acquisition,
    validate_science_corpus_manifest_against_plan,
)
from eom_catalog_service.models import ContentIntakeSourceFileRecord
from eom_catalog_service.science_assessment_web_acquisition import (
    AcquiredScienceAssessmentPdf,
    ScienceAssessmentDiscovery,
    ScienceAssessmentPdfCandidate,
)
from eom_catalog_service.science_assessment_web_acquisition_checkpoint import (
    build_science_assessment_acquisition,
)
from eom_catalog_service.science_assessment_web_corpus_service import (
    MAX_INTAKE_FILES,
    ScienceAssessmentCorpusPublicationError,
    _aggregate_acquired,
    _AggregatedPdf,
    _bounded_shards,
    _build_manifest,
    _require_acquisition_projection,
    _ResolvedSource,
    _stage_intake_shard,
)
from eom_identifiers import sha256_file


def _plan() -> ScienceAssessmentWebCorpusPlan:
    value = json.loads(Path("config/science-assessment-web-corpus.v1.json").read_text())
    assert isinstance(value, dict)
    return ScienceAssessmentWebCorpusPlan.model_validate(value)


def _candidate(*, post: str, subject: str = "PHYSICS") -> ScienceAssessmentPdfCandidate:
    return ScienceAssessmentPdfCandidate(
        post_url=f"https://legendstudy.com/{post}",
        download_url=f"https://t1.daumcdn.net/file/{post}.pdf",
        link_text=f"2026학년도 6월 모의평가 {subject} 문제.pdf",
        original_filename=f"{subject}-{post}.pdf",
        subject_family=subject,
        subject_label="물리학1" if subject == "PHYSICS" else "화학1",
        issuer_type="KICE",
        administration_year=2025,
        grade=3,
        session_label="6월 모의평가",
    )


def _acquired(
    source: Path, *, post: str, digest_character: str = "a", subject: str = "PHYSICS"
) -> AcquiredScienceAssessmentPdf:
    return AcquiredScienceAssessmentPdf(
        candidate=_candidate(post=post, subject=subject),
        resolved_url=f"https://t1.daumcdn.net/file/{post}.pdf",
        source=source,
        sha256="sha256:" + digest_character * 64,
        bytes=4096,
        page_count=4,
    )


def test_aggregate_deduplicates_bytes_and_preserves_sorted_origins(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)

    aggregate = _aggregate_acquired(
        (
            _acquired(source, post="200"),
            _acquired(source, post="100"),
        )
    )

    assert tuple(aggregate) == ("sha256:" + "a" * 64,)
    document = next(iter(aggregate.values()))
    assert [value.post_url for value in document.origins] == [
        "https://legendstudy.com/100",
        "https://legendstudy.com/200",
    ]


def test_aggregate_rejects_conflicting_metadata_for_identical_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)

    with pytest.raises(ScienceAssessmentCorpusPublicationError, match="METADATA_CONFLICT"):
        _aggregate_acquired(
            (
                _acquired(source, post="100", subject="PHYSICS"),
                _acquired(source, post="200", subject="CHEMISTRY"),
            )
        )


def test_bounded_shards_are_deterministic_and_respect_file_limit(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)
    aggregate = {
        f"sha256:{index:064x}": _AggregatedPdf(
            source=source,
            sha256=f"sha256:{index:064x}",
            bytes=4096,
            page_count=1,
            original_filename=f"{index}.pdf",
            subject_family="PHYSICS",
            subject_label="물리학1",
            issuer_type="KICE",
            administration_year=2025,
            grade=3,
            session_label="6월 모의평가",
            origins=(),
        )
        for index in range(MAX_INTAKE_FILES + 1)
    }

    shards = _bounded_shards(tuple(aggregate), aggregate)

    assert tuple(map(len, shards)) == (MAX_INTAKE_FILES, 1)
    assert tuple(value for shard in shards for value in shard) == tuple(aggregate)


def test_manifest_binds_summary_plan_and_reused_source(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)
    acquired = (
        _acquired(source, post="100"),
        _acquired(source, post="200"),
    )
    aggregate = _aggregate_acquired(acquired)
    content_hash = next(iter(aggregate))
    pointer = ScienceAssessmentCorpusSourcePointer(
        intake_batch_id="intake_" + "1" * 32,
        source_file_id="sourcefile_" + "2" * 32,
        artifact_id="artifact_" + "3" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        member_path="source/existing-name.pdf",
        sha256=content_hash,
    )
    plan = _plan()
    discovery = ScienceAssessmentDiscovery(
        post_count=2,
        candidates=tuple(value.candidate for value in acquired),
        rejected_link_count=0,
    )
    acquisition = build_science_assessment_acquisition(
        plan=plan,
        discovery=discovery,
        acquired=acquired,
        failures=(),
        observed_at=datetime(2026, 9, 25, 16, 30, tzinfo=UTC),
    )

    manifest = _build_manifest(
        plan=plan,
        acquisition=acquisition,
        discovery=discovery,
        aggregate=aggregate,
        failures=(),
        resolved={
            content_hash: _ResolvedSource(
                pointer=pointer,
                disposition="REUSED_EXISTING",
            )
        },
        new_shards=(),
    )

    assert manifest.summary.unique_document_count == 1
    assert manifest.summary.candidate_count == 2
    assert manifest.summary.duplicate_observation_count == 1
    assert manifest.summary.reused_existing_count == 1
    assert manifest.intake_shards == ()
    assert manifest.acquisition_sha256 == acquisition.acquisition_sha256
    validate_contract(
        "science-assessment-web-corpus-manifest",
        manifest.model_dump(mode="json"),
    )
    validate_science_corpus_manifest_against_plan(manifest, plan)
    validate_science_corpus_manifest_against_acquisition(manifest, acquisition)


def test_new_document_must_bind_exact_new_shard(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)
    aggregate = _aggregate_acquired((_acquired(source, post="100"),))
    content_hash = next(iter(aggregate))
    pointer = ScienceAssessmentCorpusSourcePointer(
        intake_batch_id="intake_" + "1" * 32,
        source_file_id="sourcefile_" + "2" * 32,
        artifact_id="artifact_" + "3" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        member_path=f"source/{'a' * 64}.pdf",
        sha256=content_hash,
    )
    plan = _plan()
    discovery = ScienceAssessmentDiscovery(
        post_count=1,
        candidates=(_candidate(post="100"),),
        rejected_link_count=0,
    )
    acquired = (_acquired(source, post="100"),)
    acquisition = build_science_assessment_acquisition(
        plan=plan,
        discovery=discovery,
        acquired=acquired,
        failures=(),
        observed_at=datetime(2026, 9, 25, 16, 30, tzinfo=UTC),
    )
    shard = ScienceAssessmentCorpusIntakeShard(
        ordinal=1,
        intake_batch_id=pointer.intake_batch_id,
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        source_fingerprint="sha256:" + "5" * 64,
        document_count=1,
    )

    manifest = _build_manifest(
        plan=plan,
        acquisition=acquisition,
        discovery=discovery,
        aggregate=aggregate,
        failures=(),
        resolved={
            content_hash: _ResolvedSource(
                pointer=pointer,
                disposition="NEW_INTAKE",
            )
        },
        new_shards=(shard,),
    )

    assert manifest.summary.new_intake_count == 1
    assert manifest.intake_shards == (shard,)


def test_acquisition_projection_rejects_local_observation_drift(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)
    acquired = (_acquired(source, post="100"),)
    discovery = ScienceAssessmentDiscovery(
        post_count=1,
        candidates=(acquired[0].candidate,),
        rejected_link_count=0,
    )
    acquisition = build_science_assessment_acquisition(
        plan=_plan(),
        discovery=discovery,
        acquired=acquired,
        failures=(),
    )
    drifted = (_acquired(source, post="200"),)

    with pytest.raises(
        ScienceAssessmentCorpusPublicationError,
        match="ACQUISITION_PROJECTION_MISMATCH",
    ):
        _require_acquisition_projection(acquisition, discovery, drifted, ())


def test_content_intake_source_hash_lookup_has_a_btree_index() -> None:
    indexes = {
        value.name: tuple(column.name for column in value.columns)
        for value in ContentIntakeSourceFileRecord.__table__.indexes
    }

    assert indexes["ix_content_intake_source_sha256"] == ("sha256",)


def test_intake_shard_staging_is_content_addressed_and_replayable(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)
    content_hash = sha256_file(source)
    acquired = AcquiredScienceAssessmentPdf(
        candidate=_candidate(post="100"),
        resolved_url="https://t1.daumcdn.net/file/100.pdf",
        source=source,
        sha256=content_hash,
        bytes=4096,
        page_count=4,
    )
    aggregate = _aggregate_acquired((acquired,))

    first = _stage_intake_shard(
        staging_root=tmp_path / "staging",
        plan=_plan(),
        hashes=(content_hash,),
        aggregate=aggregate,
    )
    second = _stage_intake_shard(
        staging_root=tmp_path / "staging",
        plan=_plan(),
        hashes=(content_hash,),
        aggregate=aggregate,
    )

    assert first == second
    assert tuple(value.name for value in first.iterdir()) == (
        f"{content_hash.removeprefix('sha256:')}.pdf",
    )


def test_intake_shard_staging_rejects_replay_drift(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * 4096)
    content_hash = sha256_file(source)
    acquired = AcquiredScienceAssessmentPdf(
        candidate=_candidate(post="100"),
        resolved_url="https://t1.daumcdn.net/file/100.pdf",
        source=source,
        sha256=content_hash,
        bytes=4096,
        page_count=4,
    )
    aggregate = _aggregate_acquired((acquired,))
    directory = _stage_intake_shard(
        staging_root=tmp_path / "staging",
        plan=_plan(),
        hashes=(content_hash,),
        aggregate=aggregate,
    )
    next(directory.iterdir()).write_bytes(b"drift")

    with pytest.raises(ScienceAssessmentCorpusPublicationError, match="STAGING_INVALID"):
        _stage_intake_shard(
            staging_root=tmp_path / "staging",
            plan=_plan(),
            hashes=(content_hash,),
            aggregate=aggregate,
        )
