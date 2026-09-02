from __future__ import annotations

from pathlib import Path

from eom_catalog_service import item_origin_models, legacy_assessment_models
from eom_orchestrator.models import Base
from sqlalchemy import LargeBinary

LEGACY_ASSESSMENT_TABLES = {
    "assessment_source_bundles",
    "assessment_source_bundle_revisions",
    "assessment_source_bundle_members",
    "assessment_layout_observations",
    "legacy_item_extraction_acceptances",
    "legacy_item_extraction_decisions",
    "legacy_item_corpus_coverages",
    "legacy_item_corpus_bundle_coverages",
}


def _foreign_key_targets(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in Base.metadata.tables[table_name].foreign_key_constraints
    }


def _foreign_key_names(table_name: str) -> set[str]:
    return {
        str(constraint.name)
        for constraint in Base.metadata.tables[table_name].foreign_key_constraints
        if constraint.name is not None
    }


def test_legacy_assessment_metadata_is_pointer_only_and_indexed() -> None:
    assert item_origin_models.__name__.endswith("item_origin_models")
    assert legacy_assessment_models.__name__.endswith("legacy_assessment_models")
    assert set(Base.metadata.tables) >= LEGACY_ASSESSMENT_TABLES
    forbidden_columns = {
        "bytes",
        "canonical_document",
        "content",
        "file_path",
        "image",
        "markdown",
        "nas_path",
        "payload",
        "pdf",
        "prompt",
        "result",
    }
    for table_name in LEGACY_ASSESSMENT_TABLES:
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
        assert forbidden_columns.isdisjoint(table.columns.keys())

    expected_indexes = {
        "assessment_source_bundle_revisions": {
            "ix_assessment_source_bundle_revisions_occurrence",
            "ix_assessment_source_bundle_revisions_inventory",
        },
        "assessment_source_bundle_members": {
            "ix_assessment_source_bundle_members_artifact",
            "ix_assessment_source_bundle_members_inventory",
        },
        "assessment_layout_observations": {"ix_assessment_layout_observations_bundle"},
        "legacy_item_extraction_acceptances": {"ix_legacy_item_extraction_acceptances_result"},
        "legacy_item_corpus_coverages": {"ix_legacy_item_corpus_coverages_inventory"},
        "legacy_item_corpus_bundle_coverages": {"ix_legacy_item_corpus_bundle_coverages_bundle"},
    }
    for table_name, expected in expected_indexes.items():
        actual = {
            str(index.name)
            for index in Base.metadata.tables[table_name].indexes
            if index.name is not None
        }
        assert actual >= expected


def test_legacy_assessment_metadata_uses_closed_composite_pointers() -> None:
    artifact_revision = (
        "artifact_revisions.logical_artifact_id",
        "artifact_revisions.revision_id",
    )
    occurrence_revision = (
        "assessment_occurrence_revisions.assessment_occurrence_id",
        "assessment_occurrence_revisions.assessment_occurrence_revision_id",
    )
    bundle_revision = (
        "assessment_source_bundle_revisions.assessment_source_bundle_id",
        "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
    )
    assert occurrence_revision in _foreign_key_targets("assessment_source_bundle_revisions")
    assert artifact_revision in _foreign_key_targets("assessment_source_bundle_revisions")
    assert "fk_assessment_bundle_inventory_artifact_revision_identity" in _foreign_key_names(
        "assessment_source_bundle_revisions"
    )
    assert artifact_revision in _foreign_key_targets("assessment_source_bundle_members")
    assert artifact_revision in _foreign_key_targets("assessment_layout_observations")
    assert bundle_revision in _foreign_key_targets("assessment_layout_observations")
    assert artifact_revision in _foreign_key_targets("legacy_item_corpus_coverages")
    assert bundle_revision in _foreign_key_targets("legacy_item_corpus_bundle_coverages")
    acceptance_constraints = Base.metadata.tables[
        "legacy_item_extraction_acceptances"
    ].foreign_key_constraints
    assert (
        len(
            [
                constraint
                for constraint in acceptance_constraints
                if tuple(element.target_fullname for element in constraint.elements)
                == artifact_revision
            ]
        )
        == 2
    )


def test_legacy_assessment_migration_is_additive_immutable_and_gap_safe() -> None:
    source = Path("migrations/versions/20260901_0025_legacy_assessment_bundle.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260901_0024"' in source
    for table_name in LEGACY_ASSESSMENT_TABLES:
        assert f'"{table_name}"' in source
    assert "DELETE FROM" not in source
    assert "UPDATE items" not in source
    assert "UPDATE item_revisions" not in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "BEFORE INSERT OR UPDATE OR DELETE" in source
    assert "immutable legacy assessment record cannot be changed" in source
    assert "assessment source bundle current revision pointer is invalid" in source
    assert "assessment source bundle revision sequence must advance once" in source
    assert "legacy assessment history prevents safe downgrade" in source
    for constraint_name in (
        "fk_assessment_source_bundle_occurrence_revision_identity",
        "fk_assessment_bundle_inventory_artifact_revision_identity",
        "fk_assessment_source_bundle_member_artifact_revision_identity",
        "fk_assessment_layout_bundle_revision_identity",
        "fk_assessment_layout_artifact_revision_identity",
        "fk_legacy_item_acceptance_result_artifact_revision_identity",
        "fk_legacy_item_acceptance_artifact_revision_identity",
        "fk_legacy_item_corpus_coverage_artifact_revision_identity",
        "fk_legacy_item_corpus_coverage_bundle_revision_identity",
    ):
        assert constraint_name in source
