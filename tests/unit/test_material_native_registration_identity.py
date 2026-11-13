"""Existing Registry keys fence one native source across later Excel metadata."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.material_native_files import (
    MaterialNativeItemBinding,
    material_native_registration_key,
)
from eom_identifiers import content_sha256

from tests.unit.test_material_native_files import binding_data

ACTOR = "operator_" + "1" * 32


def binding(value):
    value = deepcopy(value)
    value["binding_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "binding_sha256"}
    )
    return MaterialNativeItemBinding.model_validate(value)


def test_native_key_reuses_source_after_excel_numbers_or_material_metadata_change():
    original = binding_data()
    changed = deepcopy(original)
    changed["material_id"] = "material_" + "a" * 32
    changed["material_revision_id"] = "materialrev_" + "b" * 32
    changed["unit_key"] = "materialunit_" + "c" * 32
    changed["workbook"]["row_sha256"] = "sha256:" + "d" * 64
    changed["workbook"]["workbook"]["sha256"] = "sha256:" + "e" * 64
    changed["source_metadata"]["external_number"] = "12345"
    changed["source_metadata"]["original_unit"] = "추후 정정된 원본 단원"
    changed["source_metadata"]["source_name"] = "추후 정정된 문항명"
    key = material_native_registration_key(ACTOR, binding(original))
    assert key == material_native_registration_key(ACTOR, binding(changed))
    assert key.startswith("material-native-item:") and len(key) < 200


@pytest.mark.parametrize("part", ["operator", "source", "exam", "number"])
def test_native_key_keeps_actual_owner_and_distinct_source_questions_separate(part):
    original = binding_data()
    changed = deepcopy(original)
    actor = ACTOR
    if part == "operator":
        actor = "operator_" + "a" * 32
    elif part == "source":
        changed["question"]["original_source_sha256"] = "sha256:" + "d" * 64
    elif part == "exam":
        changed["exam_key"] = "another-exam"
    else:
        changed["item_number"] = 2
        changed["printed_label"] = "2"
    assert material_native_registration_key(ACTOR, binding(original)) != (
        material_native_registration_key(actor, binding(changed))
    )
