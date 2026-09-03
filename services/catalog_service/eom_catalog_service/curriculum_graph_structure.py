"""Deterministic bridge from the reviewed Integrated Science outline to Graph structure V2."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
    AnalysisCurriculumBinding,
    ApprovedItemCurriculumAlignmentBinding,
    CurriculumUnitBindingV2,
    EducationalDocumentKnowledgeSourceV4,
    KnowledgeGraphStructureManifestV2,
    KnowledgeGraphStructureManifestV3,
    load_integrated_science_editorial_outline,
)
from eom_identifiers import content_sha256

from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal

INTEGRATED_SCIENCE_FRAMEWORK_KEY = "eom-integrated-science-editorial"


class CurriculumGraphStructureError(ValueError):
    pass


def _typed_id(prefix: str, value: dict[str, object]) -> str:
    return prefix + content_sha256(value).removeprefix("sha256:")[:32]


def integrated_science_framework_revision_id() -> str:
    outline = load_integrated_science_editorial_outline()
    return _typed_id(
        "curriculumrev_",
        {
            "framework_key": INTEGRATED_SCIENCE_FRAMEWORK_KEY,
            "outline_key": outline.outline_key,
            "outline_revision": outline.outline_revision,
            "outline_sha256": INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
        },
    )


def integrated_science_curriculum_units() -> tuple[CurriculumUnitBindingV2, ...]:
    outline = load_integrated_science_editorial_outline()
    framework_revision_id = integrated_science_framework_revision_id()
    values: list[CurriculumUnitBindingV2] = []
    unit_id_by_key: dict[str, str] = {}
    for volume in outline.volumes:
        unit_id_by_key[volume.key] = _typed_id(
            "currunit_",
            {"framework_revision_id": framework_revision_id, "unit_key": volume.key},
        )
    for unit in outline.units:
        unit_id_by_key[unit.key] = _typed_id(
            "currunit_",
            {"framework_revision_id": framework_revision_id, "unit_key": unit.key},
        )
    for volume in outline.volumes:
        values.append(
            CurriculumUnitBindingV2(
                framework_revision_id=framework_revision_id,
                curriculum_unit_id=unit_id_by_key[volume.key],
                unit_key=volume.key,
                unit_code=volume.code,
                label=volume.label,
                node_stable_key=volume.graph_stable_key,
                parent_unit_id=None,
                unit_level=cast(
                    Literal["MAJOR", "MIDDLE", "MINOR", "ACHIEVEMENT_STANDARD"],
                    str(volume.graph_level),
                ),
                ordinal=volume.ordinal,
            )
        )
    for unit in outline.units:
        values.append(
            CurriculumUnitBindingV2(
                framework_revision_id=framework_revision_id,
                curriculum_unit_id=unit_id_by_key[unit.key],
                unit_key=unit.key,
                unit_code=unit.code,
                label=unit.label,
                node_stable_key=unit.graph_stable_key,
                parent_unit_id=unit_id_by_key[unit.parent_key],
                unit_level=cast(
                    Literal["MAJOR", "MIDDLE", "MINOR", "ACHIEVEMENT_STANDARD"],
                    str(unit.graph_level),
                ),
                ordinal=unit.ordinal,
            )
        )
    return tuple(sorted(values, key=lambda item: item.unit_key))


def build_integrated_science_structure_manifest(
    analyses: tuple[AcceptedAnalysisProposal, ...],
    *,
    reviewed_by_operator_id: str,
    created_at: datetime,
) -> KnowledgeGraphStructureManifestV2:
    if not analyses:
        raise CurriculumGraphStructureError("at least one accepted analysis is required")
    run_ids = tuple(sorted(analysis.analysis_run_id for analysis in analyses))
    if len(run_ids) != len(set(run_ids)):
        raise CurriculumGraphStructureError("accepted analysis run IDs must be unique")
    units = integrated_science_curriculum_units()
    middle_by_code = {unit.unit_code: unit for unit in units if unit.unit_level == "MINOR"}
    bindings: list[AnalysisCurriculumBinding] = []
    for analysis in sorted(analyses, key=lambda item: item.analysis_run_id):
        source = analysis.source
        if not isinstance(source, EducationalDocumentKnowledgeSourceV4):
            raise CurriculumGraphStructureError(
                "Integrated Science structure requires multimodal document analyses"
            )
        if not source.curriculum_unit_keys:
            continue
        try:
            unit_ids = tuple(
                sorted(
                    middle_by_code[code].curriculum_unit_id for code in source.curriculum_unit_keys
                )
            )
        except KeyError as exc:
            raise CurriculumGraphStructureError(
                "analysis source references an unknown curriculum code"
            ) from exc
        bindings.append(
            AnalysisCurriculumBinding(
                analysis_run_id=analysis.analysis_run_id,
                curriculum_unit_ids=unit_ids,
            )
        )
    outline = load_integrated_science_editorial_outline()
    framework_revision_id = integrated_science_framework_revision_id()
    structure_manifest_id = _typed_id(
        "graphstructure_",
        {
            "framework_revision_id": framework_revision_id,
            "source_analysis_run_ids": list(run_ids),
        },
    )
    value = {
        "schema_version": "knowledge-graph-structure-manifest/2.0",
        "structure_manifest_id": structure_manifest_id,
        "framework_key": INTEGRATED_SCIENCE_FRAMEWORK_KEY,
        "framework_revision_id": framework_revision_id,
        "outline_key": outline.outline_key,
        "outline_revision": outline.outline_revision,
        "outline_sha256": INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
        "source_analysis_run_ids": list(run_ids),
        "curriculum_units": [unit.model_dump(mode="json") for unit in units],
        "analysis_curriculum_bindings": [binding.model_dump(mode="json") for binding in bindings],
        "item_elements": [],
        "reviewed_by_operator_id": reviewed_by_operator_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    return KnowledgeGraphStructureManifestV2.model_validate(value)


def validate_integrated_science_structure_manifest(
    structure: KnowledgeGraphStructureManifestV2,
) -> None:
    outline = load_integrated_science_editorial_outline()
    if (
        structure.framework_key != INTEGRATED_SCIENCE_FRAMEWORK_KEY
        or structure.framework_revision_id != integrated_science_framework_revision_id()
        or structure.outline_key != outline.outline_key
        or structure.outline_revision != outline.outline_revision
        or structure.outline_sha256 != INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256
        or structure.curriculum_units != integrated_science_curriculum_units()
    ):
        raise CurriculumGraphStructureError(
            "structure manifest differs from the reviewed Integrated Science outline"
        )


def extend_integrated_science_structure_manifest_with_item_alignments(
    base: KnowledgeGraphStructureManifestV2 | KnowledgeGraphStructureManifestV3,
    additions: tuple[ApprovedItemCurriculumAlignmentBinding, ...],
    *,
    reviewed_by_operator_id: str,
    created_at: datetime,
) -> KnowledgeGraphStructureManifestV3:
    """Append immutable approved-Item alignments while preserving reviewed framework data."""

    validate_integrated_science_structure_manifest(base)
    existing = (
        base.approved_item_curriculum_bindings
        if isinstance(base, KnowledgeGraphStructureManifestV3)
        else ()
    )
    combined = tuple(sorted((*existing, *additions), key=lambda item: item.analysis_run_id))
    run_ids = tuple(
        sorted(
            {
                *base.source_analysis_run_ids,
                *(binding.analysis_run_id for binding in additions),
            }
        )
    )
    if len(combined) != len({binding.analysis_run_id for binding in combined}) or len(
        combined
    ) != len({binding.item_revision_id for binding in combined}):
        raise CurriculumGraphStructureError(
            "approved Item alignment additions duplicate a run or Item revision"
        )
    structure_manifest_id = _typed_id(
        "graphstructure_",
        {
            "framework_revision_id": base.framework_revision_id,
            "source_analysis_run_ids": list(run_ids),
            "approved_item_alignment_hashes": [binding.alignment_sha256 for binding in combined],
        },
    )
    value = {
        **base.model_dump(
            mode="json",
            exclude={
                "schema_version",
                "structure_manifest_id",
                "source_analysis_run_ids",
                "reviewed_by_operator_id",
                "created_at",
                "manifest_sha256",
                "approved_item_curriculum_bindings",
            },
        ),
        "schema_version": "knowledge-graph-structure-manifest/3.0",
        "structure_manifest_id": structure_manifest_id,
        "source_analysis_run_ids": list(run_ids),
        "approved_item_curriculum_bindings": [
            binding.model_dump(mode="json") for binding in combined
        ],
        "reviewed_by_operator_id": reviewed_by_operator_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    return KnowledgeGraphStructureManifestV3.model_validate(value)
