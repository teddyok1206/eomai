from __future__ import annotations

import hashlib
from collections import defaultdict
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import ScienceAssessmentCorpusDocument
from eom_catalog_service import science_visual_pilot as planning
from eom_catalog_service.science_visual_pilot import (
    ScienceVisualPilotPlanningError,
    build_science_visual_pilot_plan_v2,
    build_science_visual_pilot_plan_v3,
    select_science_visual_campaign_shard_sources,
    select_science_visual_pilot_sources,
)
from eom_image_contracts import (
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotPlan,
    ScienceVisualLocatorPolicyV2,
)

from tests.unit.test_science_corpus_visual_contracts import _authorization_value, _plan_value


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


def test_campaign_shards_are_deterministic_and_do_not_reuse_source_pdfs() -> None:
    documents = tuple(_document(index) for index in range(360))
    seed = "sha256:" + "a" * 64
    shards = tuple(
        select_science_visual_campaign_shard_sources(
            documents,
            selection_seed_sha256=seed,
            campaign_shard_index=index,
            campaign_shard_count=3,
            source_limit=36,
            page_limit=192,
        )
        for index in range(3)
    )
    replay = select_science_visual_campaign_shard_sources(
        tuple(reversed(documents)),
        selection_seed_sha256=seed,
        campaign_shard_index=1,
        campaign_shard_count=3,
        source_limit=36,
        page_limit=192,
    )

    assert shards[1] == replay
    all_hashes = [source.pdf.sha256 for shard in shards for source in shard]
    assert len(all_hashes) == 108
    assert len(all_hashes) == len(set(all_hashes))
    assert all(sum(source.page_count for source in shard) <= 192 for shard in shards)


def test_campaign_shard_rejects_an_invalid_coordinate() -> None:
    with pytest.raises(ScienceVisualPilotPlanningError, match="CAMPAIGN_SHARD_INVALID"):
        select_science_visual_campaign_shard_sources(
            tuple(_document(index) for index in range(120)),
            selection_seed_sha256="sha256:" + "a" * 64,
            campaign_shard_index=2,
            campaign_shard_count=2,
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


def test_successor_plan_preserves_selection_and_adds_exact_locator_policy(monkeypatch) -> None:
    predecessor = LocalImageScienceCorpusVisualPilotPlan.model_validate(_plan_value())
    authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
        _authorization_value()
    )
    monkeypatch.setattr(
        planning,
        "build_science_visual_pilot_plan",
        lambda **_kwargs: predecessor,
    )
    locator_policy = ScienceVisualLocatorPolicyV2(
        max_candidates_per_page=4,
        max_candidates_per_source=12,
        maximum_redaction_area_milli=350,
        minimum_interior_ink_milli=8,
        maximum_border_ink_fraction_milli=650,
        minimum_aspect_ratio_milli=200,
        maximum_aspect_ratio_milli=5000,
    )

    successor = build_science_visual_pilot_plan_v2(
        corpus=SimpleNamespace(documents=()),  # type: ignore[arg-type]
        corpus_manifest=predecessor.corpus_manifest,
        authorization=authorization,
        authorization_pointer=predecessor.training_authorization,
        selection_seed_sha256=predecessor.selection_seed_sha256,
        guidance_authorities=predecessor.guidance_authorities,
        tools=predecessor.tools,
        source_commit=predecessor.guidance_authorities[0].source_commit,
        created_at=predecessor.created_at,
        created_by=predecessor.created_by,
        locator_policy=locator_policy,
    )

    assert successor.schema_version.endswith("/1.1")
    assert successor.locator_revision.endswith("/1.1")
    assert successor.locator_policy == locator_policy
    assert successor.selected_sources == predecessor.selected_sources
    assert successor.pilot_id != predecessor.pilot_id
    assert successor.plan_sha256 != predecessor.plan_sha256


def test_campaign_plan_pins_coordinates_and_replaces_only_the_selected_shard(monkeypatch) -> None:
    predecessor = LocalImageScienceCorpusVisualPilotPlan.model_validate(_plan_value())
    authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
        _authorization_value()
    )
    locator_policy = ScienceVisualLocatorPolicyV2(
        max_candidates_per_page=4,
        max_candidates_per_source=12,
        maximum_redaction_area_milli=350,
        minimum_interior_ink_milli=8,
        maximum_border_ink_fraction_milli=650,
        minimum_aspect_ratio_milli=200,
        maximum_aspect_ratio_milli=5000,
    )
    monkeypatch.setattr(
        planning,
        "build_science_visual_pilot_plan",
        lambda **_kwargs: predecessor,
    )
    monkeypatch.setattr(
        planning,
        "select_science_visual_campaign_shard_sources",
        lambda *_args, **_kwargs: predecessor.selected_sources,
    )

    campaign = build_science_visual_pilot_plan_v3(
        corpus=SimpleNamespace(documents=()),  # type: ignore[arg-type]
        corpus_manifest=predecessor.corpus_manifest,
        authorization=authorization,
        authorization_pointer=predecessor.training_authorization,
        selection_seed_sha256=predecessor.selection_seed_sha256,
        campaign_shard_index=1,
        campaign_shard_count=3,
        guidance_authorities=predecessor.guidance_authorities,
        tools=predecessor.tools,
        source_commit=predecessor.guidance_authorities[0].source_commit,
        created_at=predecessor.created_at,
        created_by=predecessor.created_by,
        locator_policy=locator_policy,
    )
    assert campaign.schema_version.endswith("/1.2")
    assert campaign.campaign_shard_index == 1
    assert campaign.campaign_shard_count == 3
    assert campaign.selected_sources == predecessor.selected_sources
