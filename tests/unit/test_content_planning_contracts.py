"""Excel structural cases without workbook contents or production data."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.content_planning import ContentEditionCompositionV1, ContentPrintScopeV1
from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyDraftV3,
    CuratedDocumentAssemblyManifestV2,
    logical_slot_target_key,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.content_planning_fixtures import (
    SHA,
    TIME,
    composition,
    draft,
    form,
    identifier,
    item_target,
    section,
    slot,
    source_target,
)


@pytest.mark.parametrize("count", [0, 1, 20, 240, 300, 1200])
def test_real_workbook_sizes_and_duplicates_are_valid(count: int) -> None:
    body = draft(count)
    validate_contract("curated-document-assembly-draft-v3", body)
    parsed = CuratedDocumentAssemblyDraftV3.model_validate(body)
    assert len(parsed.placements) == count
    assert len({row.placement_id for row in parsed.placements}) == count
    # All are intentional repeated uses, not duplicate identities.
    assert len({logical_slot_target_key(row.target) for row in parsed.placements}) == bool(count)


def test_empty_source_registered_and_past_exam_can_coexist() -> None:
    body = draft(0)
    targets = [
        {"placement_kind": "EMPTY"},
        source_target(),
        item_target(),
        {**item_target(), "placement_kind": "PAST_EXAM_ITEM_REVISION"},
    ]
    body["placements"] = [slot(index, target=target) for index, target in enumerate(targets, 1)]
    validate_contract("curated-document-assembly-draft-v3", body)
    value = CuratedDocumentAssemblyDraftV3.model_validate(body)
    assert value.placements[0].points_milli is None
    assert logical_slot_target_key(value.placements[0].target) is None
    assert logical_slot_target_key(value.placements[2].target) == logical_slot_target_key(
        value.placements[3].target
    )


@pytest.mark.parametrize(
    "bad_target",
    [
        {"placement_kind": "EMPTY", "item_id": identifier("item")},
        {**source_target(), "edition": 1},
        {**source_target(), "source_format": "PDF"},
        {**item_target(), "item_manifest_sha256": "a" * 64},
        {**item_target(), "item_revision_id": identifier("graphrev")},
        {**item_target(), "content": "a complete item must not travel here"},
        {"placement_kind": "REGISTERED_ITEM_REVISION"},
    ],
)
def test_malformed_targets_fail_schema_and_model(bad_target: dict) -> None:
    body = draft(1)
    body["placements"][0]["target"] = bad_target
    with pytest.raises(SchemaValidationError):
        validate_contract("curated-document-assembly-draft-v3", body)
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV3.model_validate(body)


@pytest.mark.parametrize(
    "field,bad_value", [("position", 3), ("placement_id", identifier("placement", 1))]
)
def test_position_and_occurrence_not_target_are_unique(field: str, bad_value: object) -> None:
    body = draft(2)
    body["placements"][1][field] = bad_value
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV3.model_validate(body)


@pytest.mark.parametrize("bad_value", [True, "1", -1, 0.5])
def test_points_and_positions_do_not_coerce(bad_value: object) -> None:
    body = draft(1)
    body["placements"][0]["points_milli"] = bad_value
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV3.model_validate(body)


def test_resolved_external_preserves_selection_and_exact_bytes_pointer() -> None:
    selection = source_target()
    resolved = {
        **selection,
        "external_number": "10001",
        "source_file_id": identifier("sourcefile"),
        "document_artifact": {
            "artifact_id": identifier("artifact"),
            "artifact_revision_id": identifier("rev"),
            "member_path": "source/item.hwpx",
            "schema_ref": "eom://schemas/content-intake/source-file/1.0",
            "media_type": "application/vnd.hancom.hwpx",
            "sha256": SHA,
        },
        "document_size_bytes": 100,
    }
    body = {
        "schema_version": "curated-document-assembly-manifest/2.0",
        "assembly_id": identifier("assembly"),
        "assembly_revision_id": identifier("assemblyrev"),
        "revision_number": 1,
        "previous_revision_id": None,
        "selection_sha256": SHA,
        "placements": [slot(1, target=resolved)],
        "created_by": identifier("operator"),
        "created_at": TIME,
    }
    body["manifest_sha256"] = content_sha256(body)
    validate_contract("curated-document-assembly-manifest-v2", body)
    parsed = CuratedDocumentAssemblyManifestV2.model_validate(body)
    assert parsed.placements[0].selection().target.model_dump() == selection
    body["placements"][0]["target"]["document_artifact"]["sha256"] = "sha256:" + "b" * 64
    with pytest.raises(ValidationError, match="hash differs"):
        CuratedDocumentAssemblyManifestV2.model_validate(body)


@pytest.mark.parametrize("count", [0, 1, 20, 56, 60])
def test_arbitrary_content_structure_and_twenty_rounds(count: int) -> None:
    body = composition([section(n, n) for n in range(1, count + 1)])
    validate_contract("content-edition-composition-v1", body)
    assert len(ContentEditionCompositionV1.model_validate(body).sections) == count


def test_workbook_week_day_hierarchy_has_1200_slots() -> None:
    sections = []
    for week in range(1, 11):
        group = section(week * 100, week)
        group.update(kind="GROUP", form=None, label=f"{week}주")
        sections.append(group)
        for day in range(1, 7):
            sections.append(section(week * 100 + day, day, week * 100))
    body = composition(sections)
    validate_contract("content-edition-composition-v1", body)
    parsed = ContentEditionCompositionV1.model_validate(body)
    assert sum(row.form.placement_count for row in parsed.sections if row.form) == 1200


@pytest.mark.parametrize(
    "case",
    ["cycle", "missing_parent", "form_parent", "repeat_form", "ordinal", "duplicate", "preorder"],
)
def test_invalid_section_topology_fails(case: str) -> None:
    group = {**section(1), "kind": "GROUP", "form": None}
    rows = [group, section(2, 1, 1), section(3, 2)]
    if case == "cycle":
        rows[0].update(parent_id=identifier("section", 1))
    elif case == "missing_parent":
        rows[1].update(parent_id=identifier("section", 9))
    elif case == "form_parent":
        rows[1].update(parent_id=identifier("section", 3))
    elif case == "repeat_form":
        rows[2]["form"] = rows[1]["form"]
    elif case == "ordinal":
        rows[1]["ordinal"] = 2
    elif case == "duplicate":
        rows[2]["section_id"] = rows[1]["section_id"]
    else:
        rows = [rows[0], rows[2], rows[1]]
    with pytest.raises(ValidationError):
        ContentEditionCompositionV1.model_validate(composition(rows))


def test_metadata_correction_is_revisioned_and_pins_old_year() -> None:
    old = composition()
    new = composition(
        deliverable_revision_id=identifier("delivrev", 2),
        revision_number=2,
        previous_revision_id=old["deliverable_revision_id"],
        academic_year=2028,
    )
    before = ContentEditionCompositionV1.model_validate(old)
    after = ContentEditionCompositionV1.model_validate(new)
    assert before.academic_year == 2027
    assert after.academic_year == 2028
    assert before.edition_id == after.edition_id
    assert before.composition_sha256 != after.composition_sha256
    mutated = deepcopy(old)
    mutated["academic_year"] = 2028
    with pytest.raises(ValidationError, match="hash differs"):
        ContentEditionCompositionV1.model_validate(mutated)


def test_print_scope_has_exact_path_and_hash_not_latest_product_reference() -> None:
    body = {
        "schema_version": "content-print-scope/1.0",
        "deliverable_id": identifier("deliverable"),
        "edition_id": identifier("edition"),
        "content_title": "학교 시험지",
        "edition_label": "초판",
        "academic_year": 2027,
        "forms": [
            {
                "section_id": identifier("section"),
                "path": [{"section_id": identifier("section"), "label": "1회차"}],
                "form": form(),
                "numbering": "RESET_PER_SECTION",
                "start_number": 1,
            }
        ],
    }
    body["scope_sha256"] = content_sha256(body)
    validate_contract("content-print-scope-v1", body)
    parsed = ContentPrintScopeV1.model_validate(body)
    assert parsed.forms[0].form.form_revision_id == identifier("formrev")
    body["forms"][0]["path"][0]["label"] = "2회차"
    with pytest.raises(ValidationError, match="hash differs"):
        ContentPrintScopeV1.model_validate(body)


def test_released_predecessors_still_reject_repeats_and_over_200() -> None:
    from eom_catalog_contracts.curated_document_assembly_draft import CuratedDocumentAssemblyDraftV1

    repeated = [{"position": n, **item_target()} for n in (1, 2)]
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV1.model_validate(
            {
                "schema_version": "curated-document-assembly-draft/1.0",
                "placements": repeated,
            }
        )
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV1.model_validate(
            {
                "schema_version": "curated-document-assembly-draft/1.0",
                "placements": [{"position": n, **item_target(n)} for n in range(1, 202)],
            }
        )


def test_print_record_is_explicit_user_fact_and_output_must_match_scope() -> None:
    from eom_catalog_contracts.content_print_record import ContentPrintRecordV1
    from eom_catalog_service.content_planning_layout import select_print_scope

    edition = ContentEditionCompositionV1.model_validate(composition())
    scope = select_print_scope(edition, (identifier("section"),))
    body = {
        "schema_version": "content-print-record/1.0",
        "print_record_id": identifier("print"),
        "deliverable_revision_id": edition.deliverable_revision_id,
        "composition_sha256": edition.composition_sha256,
        "scope": scope.model_dump(mode="json"),
        "origin": "USER_RECORDED",
        "intent": "INITIAL",
        "predecessor_print_record_id": None,
        "printed_on": None,
        "recorded_at": TIME,
        "recorded_by": identifier("operator"),
        "note": "",
        "output": None,
    }
    body["record_sha256"] = content_sha256(body)
    validate_contract("content-print-record-v1", body)
    record = ContentPrintRecordV1.model_validate(body)
    assert record.output is None
    assert record.origin == "USER_RECORDED"
    for changes in (
        {"origin": "BUILD_COMPLETED"},
        {"intent": "REPRINT"},
        {"predecessor_print_record_id": identifier("print", 2)},
        {"intent": "CORRECTION", "predecessor_print_record_id": identifier("print")},
        {
            "output": {
                "hwpx_build_id": identifier("hwpxbuild"),
                "scope_sha256": "sha256:" + "b" * 64,
                "artifact_id": identifier("artifact"),
                "artifact_revision_id": identifier("rev"),
                "artifact_sha256": SHA,
                "output_sha256": SHA,
            }
        },
    ):
        changed = {key: value for key, value in body.items() if key != "record_sha256"}
        changed.update(changes)
        changed["record_sha256"] = content_sha256(changed)
        with pytest.raises(ValidationError):
            ContentPrintRecordV1.model_validate(changed)
