from __future__ import annotations

import hashlib
from collections import defaultdict

import pytest
from eom_catalog_contracts import ScienceAssessmentCorpusDocument
from eom_catalog_service.science_visual_pilot import (
    ScienceVisualPilotPlanningError,
    select_science_visual_pilot_sources,
)


def _document(index: int) -> ScienceAssessmentCorpusDocument:
    digest = hashlib.sha256(f"science-visual-source-{index}".encode()).hexdigest()
    subject = (
        "CHEMISTRY",
        "EARTH_SCIENCE",
        "GENERAL_SCIENCE",
        "INTEGRATED_SCIENCE",
        "LIFE_SCIENCE",
        "PHYSICS",
    )[index % 6]
    issuer = "KICE" if index % 2 else "EDUCATION_AUTHORITY"
    year = 2000 + index // 12
    session = f"SESSION_{index:03d}"
    return ScienceAssessmentCorpusDocument.model_validate(
        {
            "document_id": "sciencedoc_" + digest[:32],
            "sha256": "sha256:" + digest,
            "bytes": 4096 + index,
            "page_count": index % 5 + 1,
            "original_filename": f"science-{index:03d}.pdf",
            "media_type": "application/pdf",
            "document_role": "PROBLEM_DOCUMENT",
            "subject_family": subject,
            "subject_label": subject,
            "issuer_type": issuer,
            "administration_year": year,
            "grade": 3,
            "session_label": session,
            "publication_disposition": "REUSED_EXISTING",
            "origins": (
                {
                    "post_url": f"https://legendstudy.com/post/{index}",
                    "download_url": f"https://files.example.test/{index}.pdf",
                    "resolved_url": f"https://files.example.test/{index}.pdf",
                    "link_text": f"science {index}",
                },
            ),
            "source": {
                "intake_batch_id": "intake_" + f"{index + 1:032x}",
                "source_file_id": "sourcefile_" + f"{index + 1:032x}",
                "artifact_id": "artifact_" + f"{index + 1:032x}",
                "artifact_revision_id": "rev_" + f"{index + 1:032x}",
                "member_path": f"source/{year}/{session}/problem.pdf",
                "sha256": "sha256:" + digest,
            },
        }
    )


def test_selection_is_deterministic_stratified_and_group_safe() -> None:
    documents = tuple(_document(index) for index in range(120))
    seed = "sha256:" + "5" * 64

    first = select_science_visual_pilot_sources(
        documents,
        selection_seed_sha256=seed,
        source_limit=36,
        page_limit=192,
    )
    second = select_science_visual_pilot_sources(
        tuple(reversed(documents)),
        selection_seed_sha256=seed,
        source_limit=36,
        page_limit=192,
    )

    assert first == second
    assert len(first) == 36
    assert sum(value.page_count for value in first) <= 192
    assert {value.partition for value in first} == {"HOLDOUT", "TRAIN", "VALIDATION"}
    assert {value.subject_family for value in first} == {
        "CHEMISTRY",
        "EARTH_SCIENCE",
        "GENERAL_SCIENCE",
        "INTEGRATED_SCIENCE",
        "LIFE_SCIENCE",
        "PHYSICS",
    }
    partitions_by_group: dict[str, set[str]] = defaultdict(set)
    for source in first:
        partitions_by_group[source.exam_group_sha256].add(source.partition)
    assert all(len(partitions) == 1 for partitions in partitions_by_group.values())


def test_selection_rejects_duplicate_pdf_identity() -> None:
    documents = tuple(_document(index) for index in range(24))

    with pytest.raises(
        ScienceVisualPilotPlanningError,
        match="SCIENCE_VISUAL_PILOT_CORPUS_INVALID",
    ):
        select_science_visual_pilot_sources(
            (*documents, documents[0]),
            selection_seed_sha256="sha256:" + "5" * 64,
            source_limit=12,
            page_limit=60,
        )


def test_selection_fails_closed_when_page_budget_cannot_fill_partition_quotas() -> None:
    documents = tuple(_document(index) for index in range(24))

    with pytest.raises(
        ScienceVisualPilotPlanningError,
        match="SCIENCE_VISUAL_PILOT_POPULATION_INSUFFICIENT",
    ):
        select_science_visual_pilot_sources(
            documents,
            selection_seed_sha256="sha256:" + "5" * 64,
            source_limit=12,
            page_limit=12,
        )
