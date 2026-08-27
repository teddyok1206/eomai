from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_KEY,
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_REVISION,
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
    IntegratedScienceCurriculumContractError,
    IntegratedScienceEditorialOutline,
    catalog_schema_inventory,
    integrated_science_curriculum_resolver,
    load_integrated_science_editorial_outline,
    resolve_integrated_science_curriculum_scope,
    validate_contract,
    validate_integrated_science_curriculum_scope,
)
from eom_catalog_contracts.curriculum import (
    _parse_integrated_science_editorial_outline,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SCHEMA = (
    REPOSITORY_ROOT / "schemas/curriculum/integrated-science-editorial-outline-v1.schema.json"
)
CANONICAL_OUTLINE = (
    REPOSITORY_ROOT / "content/curriculum/eom-integrated-science-editorial-outline-v1.json"
)
RESOURCE_ROOT = files("eom_catalog_contracts").joinpath("resources", "curriculum")


def test_canonical_and_packaged_schema_and_outline_bytes_are_equal_and_pinned() -> None:
    schema_raw = CANONICAL_SCHEMA.read_bytes()
    outline_raw = CANONICAL_OUTLINE.read_bytes()
    assert (
        schema_raw
        == RESOURCE_ROOT.joinpath(
            "integrated-science-editorial-outline-v1.schema.json"
        ).read_bytes()
    )
    assert (
        outline_raw
        == RESOURCE_ROOT.joinpath("eom-integrated-science-editorial-outline-v1.json").read_bytes()
    )

    schema = json.loads(schema_raw)
    outline = json.loads(outline_raw)
    Draft202012Validator.check_schema(schema)
    validate_contract("integrated-science-editorial-outline", outline)
    inventory = dict(catalog_schema_inventory())
    assert schema["$id"] == "eom://schemas/knowledge/integrated-science-editorial-outline/1.0"
    assert inventory["integrated-science-editorial-outline"].sha256 == (
        "sha256:" + hashlib.sha256(schema_raw).hexdigest()
    )
    assert (
        "sha256:" + hashlib.sha256(outline_raw).hexdigest()
    ) == INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256


def test_outline_has_exact_reviewed_cardinality_levels_and_order() -> None:
    outline = load_integrated_science_editorial_outline()
    assert outline.outline_key == INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_KEY
    assert outline.outline_revision == INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_REVISION
    assert len(outline.volumes) == 2
    assert [unit.level for unit in outline.units].count("LARGE") == 6
    assert [unit.level for unit in outline.units].count("MIDDLE") == 35
    assert outline.supported_product_levels == ("LARGE", "MIDDLE")
    assert outline.unsupported_product_levels == ("SMALL",)
    assert "SMALL" not in {unit.level for unit in outline.units}
    assert tuple(unit.key for unit in outline.units[:6]) == (
        "eom.is.large.1",
        "eom.is.middle.1-1",
        "eom.is.middle.1-2",
        "eom.is.middle.1-3",
        "eom.is.middle.1-4",
        "eom.is.large.2",
    )
    assert tuple((unit.code, unit.label) for unit in outline.units[-5:]) == (
        ("6", "과학과 미래 사회"),
        ("6-(1)", "감염병과 병원체"),
        ("6-(2)", "인공지능과 과학 탐구"),
        ("6-(3)", "로봇"),
        ("6-(4)", "과학기술과 윤리"),
    )


def test_resolver_provides_constant_time_indexes_and_ordered_children() -> None:
    resolver = integrated_science_curriculum_resolver()
    assert resolver.units_by_key["eom.is.large.4"].label == "변화와 다양성"
    assert resolver.parent_by_key["eom.is.middle.2-5"] == "eom.is.large.2"
    assert tuple(unit.key for unit in resolver.ordered_children("eom.is.volume.ii")) == (
        "eom.is.large.4",
        "eom.is.large.5",
        "eom.is.large.6",
    )
    assert tuple(unit.ordinal for unit in resolver.ordered_children("eom.is.large.2")) == (
        1,
        2,
        3,
        4,
        5,
        6,
    )
    with pytest.raises(TypeError):
        resolver.units_by_key["new"] = resolver.units_by_key["eom.is.large.1"]  # type: ignore[index]


def test_scope_resolution_autofills_exact_ancestors_breadcrumb_and_provenance() -> None:
    large = resolve_integrated_science_curriculum_scope("eom.is.large.4")
    assert large.model_dump(mode="json") == {
        "outline_key": INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_KEY,
        "outline_revision": INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_REVISION,
        "outline_sha256": INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
        "selected_unit_key": "eom.is.large.4",
        "selected_level": "LARGE",
        "volume_key": "eom.is.volume.ii",
        "large_unit_key": "eom.is.large.4",
        "middle_unit_key": None,
        "graph_root_stable_key": ("curriculum.eom.editorial.integrated-science.volume-ii.large-4"),
        "breadcrumb": ["II권", "변화와 다양성"],
    }

    middle = resolve_integrated_science_curriculum_scope("eom.is.middle.4-7")
    assert middle.volume_key == "eom.is.volume.ii"
    assert middle.large_unit_key == "eom.is.large.4"
    assert middle.middle_unit_key == "eom.is.middle.4-7"
    assert middle.graph_root_stable_key.endswith("volume-ii.large-4.middle-7")
    assert middle.breadcrumb == ("II권", "변화와 다양성", "물질 변화에서의 에너지 출입")
    assert validate_integrated_science_curriculum_scope(middle) is middle


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("volume_key", "eom.is.volume.i"),
        ("large_unit_key", "eom.is.large.5"),
        ("graph_root_stable_key", "curriculum.integrated-science.forged"),
        ("breadcrumb", ("II권", "잘못된 경로", "물질 변화에서의 에너지 출입")),
        ("outline_sha256", "sha256:" + "0" * 64),
    ],
)
def test_forged_scope_pointer_fields_fail_closed(field: str, forged_value: object) -> None:
    resolved = resolve_integrated_science_curriculum_scope("eom.is.middle.4-7")
    forged = resolved.model_copy(update={field: forged_value})
    with pytest.raises(
        IntegratedScienceCurriculumContractError, match="does not match the pinned outline"
    ):
        validate_integrated_science_curriculum_scope(forged)


@pytest.mark.parametrize("unknown_key", ["eom.is.small.placeholder", "eom.is.middle.9-9", ""])
def test_unknown_and_small_unit_keys_fail_closed(unknown_key: str) -> None:
    with pytest.raises(
        IntegratedScienceCurriculumContractError,
        match="unknown Integrated Science curriculum unit",
    ):
        resolve_integrated_science_curriculum_scope(unknown_key)


def test_parent_prefix_mismatch_and_raw_data_corruption_fail_closed() -> None:
    value = json.loads(CANONICAL_OUTLINE.read_bytes())
    value["units"][1]["parent_key"] = "eom.is.large.2"
    with pytest.raises(ValidationError, match="MIDDLE unit identity"):
        IntegratedScienceEditorialOutline.model_validate(value)

    corrupted = CANONICAL_OUTLINE.read_bytes().replace(
        "시간과 공간".encode(), "시간과 우주".encode()
    )
    with pytest.raises(IntegratedScienceCurriculumContractError, match="resource hash mismatch"):
        _parse_integrated_science_editorial_outline(corrupted)


def test_duplicate_json_keys_are_rejected_after_hash_verification() -> None:
    raw = b'{"schema_version":"x","schema_version":"x"}'
    expected_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    with pytest.raises(IntegratedScienceCurriculumContractError, match="resource is malformed"):
        _parse_integrated_science_editorial_outline(raw, expected_sha256=expected_sha256)
