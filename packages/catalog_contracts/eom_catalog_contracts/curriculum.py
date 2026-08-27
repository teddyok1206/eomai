"""Pinned Integrated Science editorial outline and deterministic scope resolution.

The graph stable keys in this catalog are reviewed reservation candidates.  They map
product LARGE to Graph MIDDLE and product MIDDLE to Graph MINOR, but their presence
does not prove that corresponding nodes have been published to any Graph revision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from types import MappingProxyType
from typing import Any, Literal, Self

from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eom_catalog_contracts.validation import CatalogSchemaError, validate_contract

INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_KEY = "eom-integrated-science-editorial-outline"
INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_REVISION = "1.0"
INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256 = (
    "sha256:f11389c8ab26c2bd5b93acf66fe92d30fea9c1d0bc7e6b91a6b6751fdccb5108"
)
_OUTLINE_RESOURCE_NAME = "eom-integrated-science-editorial-outline-v1.json"
_OUTLINE_RESOURCE_ROOT = files("eom_catalog_contracts").joinpath("resources", "curriculum")
_MIDDLE_CODE_PATTERN = re.compile(r"([1-6])-\(([1-7])\)")
_MIDDLE_COUNTS = {1: 4, 2: 6, 3: 7, 4: 7, 5: 7, 6: 4}


class IntegratedScienceCurriculumContractError(ValueError):
    """Raised when the pinned outline or a requested unit cannot be resolved safely."""


class IntegratedScienceProductLevel(StrEnum):
    LARGE = "LARGE"
    MIDDLE = "MIDDLE"


class IntegratedScienceGraphLevel(StrEnum):
    MAJOR = "MAJOR"
    MIDDLE = "MIDDLE"
    MINOR = "MINOR"


class _CurriculumFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class IntegratedScienceCurriculumVolume(_CurriculumFrozenModel):
    key: str
    code: Literal["I", "II"]
    label: Literal["I권", "II권"]
    ordinal: int = Field(ge=1, le=2)
    graph_level: Literal[IntegratedScienceGraphLevel.MAJOR]
    graph_stable_key: str


class IntegratedScienceCurriculumUnit(_CurriculumFrozenModel):
    key: str
    level: IntegratedScienceProductLevel
    code: str
    label: str = Field(min_length=1, max_length=80)
    parent_key: str
    ordinal: int = Field(ge=1, le=7)
    graph_level: Literal[IntegratedScienceGraphLevel.MIDDLE, IntegratedScienceGraphLevel.MINOR]
    graph_stable_key: str


def _volume_components(large_number: int) -> tuple[str, str]:
    if large_number <= 3:
        return "eom.is.volume.i", "volume-i"
    return "eom.is.volume.ii", "volume-ii"


class IntegratedScienceEditorialOutline(_CurriculumFrozenModel):
    schema_version: Literal["integrated-science-editorial-outline/1.0"]
    outline_key: Literal["eom-integrated-science-editorial-outline"]
    outline_revision: Literal["1.0"]
    locale: Literal["ko-KR"]
    subject_key: Literal["integrated-science"]
    subject_label: Literal["통합과학"]
    graph_mapping_status: Literal["RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF"]
    supported_product_levels: tuple[Literal["LARGE"], Literal["MIDDLE"]]
    unsupported_product_levels: tuple[Literal["SMALL"]]
    volumes: tuple[IntegratedScienceCurriculumVolume, ...]
    units: tuple[IntegratedScienceCurriculumUnit, ...]

    @model_validator(mode="after")
    def validate_reviewed_outline(self) -> Self:
        expected_volumes = (
            (
                "eom.is.volume.i",
                "I",
                "I권",
                1,
                "curriculum.eom.editorial.integrated-science.volume-i",
            ),
            (
                "eom.is.volume.ii",
                "II",
                "II권",
                2,
                "curriculum.eom.editorial.integrated-science.volume-ii",
            ),
        )
        observed_volumes = tuple(
            (volume.key, volume.code, volume.label, volume.ordinal, volume.graph_stable_key)
            for volume in self.volumes
        )
        if observed_volumes != expected_volumes:
            raise ValueError("outline must contain the exact ordered I/II volume catalog")
        if any(volume.graph_level != IntegratedScienceGraphLevel.MAJOR for volume in self.volumes):
            raise ValueError("outline volumes must map to Graph MAJOR")
        if len(self.units) != 41:
            raise ValueError("outline must contain exactly 41 selectable units")

        large_units = tuple(unit for unit in self.units if unit.level == "LARGE")
        middle_units = tuple(unit for unit in self.units if unit.level == "MIDDLE")
        if len(large_units) != 6 or len(middle_units) != 35:
            raise ValueError("outline must contain exactly 6 LARGE and 35 MIDDLE units")

        unit_keys = {unit.key for unit in self.units}
        graph_keys = {volume.graph_stable_key for volume in self.volumes}
        graph_keys.update(unit.graph_stable_key for unit in self.units)
        if len(unit_keys) != len(self.units) or len(graph_keys) != len(self.units) + 2:
            raise ValueError("outline keys and graph stable keys must be unique")

        expected_preorder: list[str] = []
        children: dict[int, list[IntegratedScienceCurriculumUnit]] = {
            number: [] for number in range(1, 7)
        }
        large_by_number: dict[int, IntegratedScienceCurriculumUnit] = {}
        for unit in self.units:
            if unit.level == "LARGE":
                if not unit.code.isascii() or not unit.code.isdigit():
                    raise ValueError("LARGE code must be an ASCII integer")
                large_number = int(unit.code)
                if large_number not in range(1, 7) or large_number in large_by_number:
                    raise ValueError("LARGE code must be unique in the range 1..6")
                volume_key, volume_slug = _volume_components(large_number)
                expected_ordinal = large_number if large_number <= 3 else large_number - 3
                expected_graph_key = (
                    "curriculum.eom.editorial.integrated-science."
                    f"{volume_slug}.large-{large_number}"
                )
                if (
                    unit.key != f"eom.is.large.{large_number}"
                    or unit.parent_key != volume_key
                    or unit.ordinal != expected_ordinal
                    or unit.graph_level != IntegratedScienceGraphLevel.MIDDLE
                    or unit.graph_stable_key != expected_graph_key
                ):
                    raise ValueError("LARGE unit identity, parent, ordinal, or graph map mismatch")
                large_by_number[large_number] = unit
                continue

            match = _MIDDLE_CODE_PATTERN.fullmatch(unit.code)
            if match is None:
                raise ValueError("MIDDLE code must use the exact N-(K) form")
            large_number, middle_number = (int(value) for value in match.groups())
            _, volume_slug = _volume_components(large_number)
            expected_graph_key = (
                "curriculum.eom.editorial.integrated-science."
                f"{volume_slug}.large-{large_number}.middle-{middle_number}"
            )
            if (
                unit.key != f"eom.is.middle.{large_number}-{middle_number}"
                or unit.parent_key != f"eom.is.large.{large_number}"
                or unit.ordinal != middle_number
                or unit.graph_level != IntegratedScienceGraphLevel.MINOR
                or unit.graph_stable_key != expected_graph_key
            ):
                raise ValueError("MIDDLE unit identity, parent, ordinal, or graph map mismatch")
            children[large_number].append(unit)

        if tuple(sorted(large_by_number)) != tuple(range(1, 7)):
            raise ValueError("outline LARGE code coverage must be exactly 1..6")
        for large_number in range(1, 7):
            expected_preorder.append(f"eom.is.large.{large_number}")
            observed_children = children[large_number]
            expected_count = _MIDDLE_COUNTS[large_number]
            if tuple(child.ordinal for child in observed_children) != tuple(
                range(1, expected_count + 1)
            ):
                raise ValueError("MIDDLE sibling ordinals must be complete and ordered")
            expected_preorder.extend(child.key for child in observed_children)
        if tuple(expected_preorder) != tuple(unit.key for unit in self.units):
            raise ValueError("outline units must use exact LARGE/MIDDLE preorder")
        return self


class IntegratedScienceCurriculumScope(_CurriculumFrozenModel):
    outline_key: Literal["eom-integrated-science-editorial-outline"]
    outline_revision: Literal["1.0"]
    outline_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    selected_unit_key: str
    selected_level: IntegratedScienceProductLevel
    volume_key: str
    large_unit_key: str
    middle_unit_key: str | None
    graph_root_stable_key: str
    breadcrumb: tuple[str, ...] = Field(min_length=2, max_length=3)


@dataclass(frozen=True, slots=True)
class IntegratedScienceCurriculumResolver:
    """Immutable indexes for O(1) lookup and stable ordered child traversal."""

    outline: IntegratedScienceEditorialOutline
    volumes_by_key: Mapping[str, IntegratedScienceCurriculumVolume]
    units_by_key: Mapping[str, IntegratedScienceCurriculumUnit]
    parent_by_key: Mapping[str, str]
    children_by_parent: Mapping[str, tuple[IntegratedScienceCurriculumUnit, ...]]

    @classmethod
    def build(
        cls, outline: IntegratedScienceEditorialOutline
    ) -> IntegratedScienceCurriculumResolver:
        volumes_by_key = {volume.key: volume for volume in outline.volumes}
        units_by_key = {unit.key: unit for unit in outline.units}
        parent_by_key = {unit.key: unit.parent_key for unit in outline.units}
        mutable_children: dict[str, list[IntegratedScienceCurriculumUnit]] = {
            key: [] for key in (*volumes_by_key, *units_by_key)
        }
        for unit in outline.units:
            mutable_children[unit.parent_key].append(unit)
        children_by_parent = {
            key: tuple(sorted(children, key=lambda child: child.ordinal))
            for key, children in mutable_children.items()
        }
        return cls(
            outline=outline,
            volumes_by_key=MappingProxyType(volumes_by_key),
            units_by_key=MappingProxyType(units_by_key),
            parent_by_key=MappingProxyType(parent_by_key),
            children_by_parent=MappingProxyType(children_by_parent),
        )

    def ordered_children(self, parent_key: str) -> tuple[IntegratedScienceCurriculumUnit, ...]:
        try:
            return self.children_by_parent[parent_key]
        except KeyError as exc:
            raise IntegratedScienceCurriculumContractError(
                f"unknown Integrated Science curriculum key: {parent_key}"
            ) from exc

    def resolve(self, selected_unit_key: str) -> IntegratedScienceCurriculumScope:
        try:
            selected = self.units_by_key[selected_unit_key]
        except KeyError as exc:
            raise IntegratedScienceCurriculumContractError(
                f"unknown Integrated Science curriculum unit: {selected_unit_key}"
            ) from exc
        if selected.level == "LARGE":
            large = selected
            middle: IntegratedScienceCurriculumUnit | None = None
        else:
            middle = selected
            large = self.units_by_key[middle.parent_key]
        volume = self.volumes_by_key[large.parent_key]
        labels: tuple[str, ...] = (volume.label, large.label)
        if middle is not None:
            labels += (middle.label,)
        return IntegratedScienceCurriculumScope(
            outline_key=self.outline.outline_key,
            outline_revision=self.outline.outline_revision,
            outline_sha256=INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
            selected_unit_key=selected.key,
            selected_level=selected.level,
            volume_key=volume.key,
            large_unit_key=large.key,
            middle_unit_key=middle.key if middle is not None else None,
            graph_root_stable_key=selected.graph_stable_key,
            breadcrumb=labels,
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = member
    return value


def _parse_integrated_science_editorial_outline(
    raw: bytes, *, expected_sha256: str = INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256
) -> IntegratedScienceEditorialOutline:
    actual_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise IntegratedScienceCurriculumContractError(
            "Integrated Science editorial outline resource hash mismatch"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("outline root must be an object")
        validate_contract("integrated-science-editorial-outline", value)
        return IntegratedScienceEditorialOutline.model_validate(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        JsonSchemaValidationError,
        CatalogSchemaError,
        ValidationError,
        ValueError,
    ) as exc:
        raise IntegratedScienceCurriculumContractError(
            "Integrated Science editorial outline resource is malformed"
        ) from exc


def _read_outline_resource(resource: Traversable) -> bytes:
    try:
        return resource.read_bytes()
    except OSError as exc:
        raise IntegratedScienceCurriculumContractError(
            "Integrated Science editorial outline package resource is unavailable"
        ) from exc


@lru_cache(maxsize=1)
def load_integrated_science_editorial_outline() -> IntegratedScienceEditorialOutline:
    """Load and validate the package-owned, raw-hash-pinned V1 outline."""

    resource = _OUTLINE_RESOURCE_ROOT.joinpath(_OUTLINE_RESOURCE_NAME)
    return _parse_integrated_science_editorial_outline(_read_outline_resource(resource))


@lru_cache(maxsize=1)
def integrated_science_curriculum_resolver() -> IntegratedScienceCurriculumResolver:
    return IntegratedScienceCurriculumResolver.build(load_integrated_science_editorial_outline())


def resolve_integrated_science_curriculum_scope(
    selected_unit_key: str,
) -> IntegratedScienceCurriculumScope:
    """Resolve any supported unit to canonical ancestors and its Graph root candidate."""

    return integrated_science_curriculum_resolver().resolve(selected_unit_key)


def validate_integrated_science_curriculum_scope(
    scope: IntegratedScienceCurriculumScope,
) -> IntegratedScienceCurriculumScope:
    """Reject any untrusted scope that differs from the pinned canonical resolution."""

    if not isinstance(scope, IntegratedScienceCurriculumScope):
        raise IntegratedScienceCurriculumContractError(
            "Integrated Science curriculum scope must use the typed shared contract"
        )
    resolved = resolve_integrated_science_curriculum_scope(scope.selected_unit_key)
    if scope != resolved:
        raise IntegratedScienceCurriculumContractError(
            "Integrated Science curriculum scope does not match the pinned outline"
        )
    return scope
