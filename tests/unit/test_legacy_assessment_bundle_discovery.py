from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts import (
    LegacySourceInventoryClassSummary,
    LegacySourceInventoryEntry,
    LegacySourceInventorySummary,
    LegacySourceInventoryV2,
    validate_contract,
)
from eom_catalog_service.legacy_assessment_bundle_discovery import (
    discover_assessment_source_bundle_proposals,
)

ZERO_SHA = "sha256:" + "0" * 64


def _entry(
    ordinal: int,
    relative_path: str,
    media_type: str,
    *,
    source_family: str = "ITEM",
) -> LegacySourceInventoryEntry:
    return LegacySourceInventoryEntry.model_validate(
        {
            "entry_key": "legacyentry_" + f"{ordinal:032x}",
            "relative_path": relative_path,
            "file_observation": "REGULAR",
            "size_bytes": 100,
            "media_type": media_type,
            "content_sha256": "sha256:" + f"{ordinal:064x}",
            "preliminary_class": "ORIGINAL_SOURCE_CANDIDATE",
            "source_family": source_family,
            "canonicality": "ORIGINAL",
            "rights_state": "UNREVIEWED",
            "relation_group_key": None,
            "exclusion_reasons": [],
        }
    )


def _inventory(entries: tuple[LegacySourceInventoryEntry, ...]) -> LegacySourceInventoryV2:
    summary = LegacySourceInventorySummary(
        original_source_candidates=LegacySourceInventoryClassSummary(
            file_count=len(entries), byte_count=100 * len(entries)
        ),
        derived_migration_evidence=LegacySourceInventoryClassSummary(file_count=0, byte_count=0),
        excluded_runtime_state=LegacySourceInventoryClassSummary(file_count=0, byte_count=0),
        total_file_count=len(entries),
        total_byte_count=100 * len(entries),
    )
    return LegacySourceInventoryV2.model_construct(
        schema_version="legacy-source-inventory/2.0",
        inventory_id="legacyinventory_" + "1" * 32,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        scanner_version="1.0.0",
        scanner_policy_revision_id="legacyinventorypolicyrev_" + "1" * 32,
        scanner_policy_sha256=ZERO_SHA,
        root_alias="EOM_LEGACY",
        root_configuration_sha256=ZERO_SHA,
        entries=entries,
        summary=summary,
        source_set_sha256=ZERO_SHA,
        inventory_sha256=ZERO_SHA,
    )


def test_discovery_groups_reviewed_directory_and_classifies_source_roles() -> None:
    directory = "items/2024/통합과학/표본시험"
    inventory = _inventory(
        (
            _entry(1, f"{directory}/문제.pdf", "application/pdf"),
            _entry(2, f"{directory}/정답해설.pdf", "application/pdf"),
            _entry(3, f"{directory}/복원본.hwpx", "application/zip"),
            _entry(
                4,
                f"{directory}/문항분류.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        )
    )

    proposals = discover_assessment_source_bundle_proposals(inventory)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert {member.proposed_role for member in proposal.members} == {
        "PROBLEM_DOCUMENT",
        "ANSWER_EXPLANATION_DOCUMENT",
        "STRUCTURED_RECONSTRUCTION",
        "ITEM_CLASSIFICATION_WORKBOOK",
    }
    assert proposal.occurrence_observation.administration_year == 2024
    assert proposal.occurrence_observation.subject_label == "통합과학"
    assert proposal.conflicts == ()
    validate_contract("assessment-source-bundle-proposal", proposal.model_dump(mode="json"))


def test_discovery_is_deterministic_and_uses_ordered_keyed_groups() -> None:
    inventory = _inventory(
        (
            _entry(1, "items/B/문제.pdf", "application/pdf"),
            _entry(2, "items/B/정답.pdf", "application/pdf"),
            _entry(3, "items/a/문제.pdf", "application/pdf"),
            _entry(4, "items/a/정답.pdf", "application/pdf"),
        )
    )

    first = discover_assessment_source_bundle_proposals(inventory)
    second = discover_assessment_source_bundle_proposals(inventory)

    assert tuple(value.occurrence_observation.exam_family_label for value in first) == ("a", "B")
    assert tuple(value.proposal_sha256 for value in first) == tuple(
        value.proposal_sha256 for value in second
    )


def test_discovery_records_missing_and_ambiguous_sources_instead_of_guessing() -> None:
    directory = "items/2024/물리학/모의평가"
    inventory = _inventory(
        (
            _entry(1, f"{directory}/문제.pdf", "application/pdf"),
            _entry(2, f"{directory}/문제_복사.pdf", "application/pdf"),
        )
    )

    (proposal,) = discover_assessment_source_bundle_proposals(inventory)

    assert {(value.field_path, value.conflict_kind) for value in proposal.conflicts} == {
        ("members.problem_document", "AMBIGUOUS_BUNDLE"),
        ("members.answer_explanation_document", "MISSING_SOURCE"),
    }
    assert all(value.blocking for value in proposal.conflicts)


def test_discovery_does_not_reclassify_non_item_sources() -> None:
    inventory = _inventory(
        (
            _entry(
                1,
                "textbooks/통합과학/교과서.pdf",
                "application/pdf",
                source_family="TEXTBOOK",
            ),
        )
    )

    assert discover_assessment_source_bundle_proposals(inventory) == ()
