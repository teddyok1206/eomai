from __future__ import annotations

from pathlib import Path

import eom_catalog_service.item_origin_models
import eom_catalog_service.models  # noqa: F401
import eom_orchestrator.models  # noqa: F401
from eom_orchestrator.models import Base
from sqlalchemy import LargeBinary, UniqueConstraint

ITEM_ORIGIN_TABLES = {
    "organizations",
    "organization_revisions",
    "organization_aliases",
    "organization_source_evidence",
    "assessment_occurrences",
    "assessment_occurrence_revisions",
    "assessment_occurrence_source_evidence",
    "item_origin_profiles",
    "item_origin_occurrences",
    "item_origin_derivations",
    "item_origin_provenance",
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


def _unique_constraint(table_name: str, constraint_name: str) -> UniqueConstraint:
    constraint = next(
        constraint
        for constraint in Base.metadata.tables[table_name].constraints
        if constraint.name == constraint_name
    )
    assert isinstance(constraint, UniqueConstraint)
    return constraint


def test_item_origin_metadata_is_pointer_only_and_indexed_for_primary_access_patterns() -> None:
    assert set(Base.metadata.tables) >= ITEM_ORIGIN_TABLES
    forbidden_columns = {
        "bytes",
        "content",
        "document",
        "file_path",
        "image",
        "markdown",
        "nas_path",
        "payload",
        "pdf",
        "prompt",
        "result",
    }
    for table_name in ITEM_ORIGIN_TABLES:
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
        assert forbidden_columns.isdisjoint(table.columns.keys())

    expected_indexes = {
        "organization_revisions": {
            "ix_organization_revisions_organization",
            "ix_organization_revisions_class",
        },
        "organization_aliases": {"ix_organization_alias_lookup"},
        "organization_source_evidence": {"ix_organization_source_evidence_owner"},
        "assessment_occurrence_revisions": {
            "ix_assessment_occurrence_lookup",
            "ix_assessment_occurrence_organization",
        },
        "assessment_occurrence_source_evidence": {"ix_assessment_occurrence_source_evidence_owner"},
        "item_origin_profiles": {
            "ix_item_origin_profiles_domain_method",
            "ix_item_origin_profiles_item",
            "ix_item_origin_profiles_organization",
        },
        "item_origin_occurrences": {"ix_item_origin_occurrences_reverse"},
        "item_origin_derivations": {"ix_item_origin_derivations_reverse"},
        "item_origin_provenance": {"ix_item_origin_provenance_reverse"},
    }
    for table_name, index_names in expected_indexes.items():
        actual = {
            str(index.name)
            for index in Base.metadata.tables[table_name].indexes
            if index.name is not None
        }
        assert index_names <= actual


def test_item_origin_metadata_closes_revision_identity_pointers() -> None:
    assert (
        "organization_revisions.organization_id",
        "organization_revisions.organization_revision_id",
    ) in _foreign_key_targets("assessment_occurrence_revisions")
    assert (
        "organization_revisions.organization_id",
        "organization_revisions.organization_revision_id",
    ) in _foreign_key_targets("item_origin_profiles")
    assert (
        "assessment_occurrence_revisions.assessment_occurrence_id",
        "assessment_occurrence_revisions.assessment_occurrence_revision_id",
    ) in _foreign_key_targets("item_origin_occurrences")
    artifact_revision = (
        "artifact_revisions.logical_artifact_id",
        "artifact_revisions.revision_id",
    )
    assert artifact_revision in _foreign_key_targets("organization_source_evidence")
    assert artifact_revision in _foreign_key_targets("assessment_occurrence_source_evidence")
    assert "fk_assessment_occ_source_evidence_artifact_revision_identity" in _foreign_key_names(
        "assessment_occurrence_source_evidence"
    )
    assert (
        "item_revisions.item_id",
        "item_revisions.item_revision_id",
    ) in _foreign_key_targets("item_origin_profiles")


def test_item_origin_nullable_business_keys_use_nulls_not_distinct() -> None:
    for table_name, constraint_name in (
        (
            "assessment_occurrence_revisions",
            "uq_assessment_occurrence_reviewed_identity",
        ),
        ("item_origin_provenance", "uq_item_origin_provenance"),
    ):
        constraint = _unique_constraint(table_name, constraint_name)
        assert constraint.dialect_options["postgresql"]["nulls_not_distinct"] is True


def test_item_origin_migration_is_additive_revisioned_and_fail_closed() -> None:
    source = Path("migrations/versions/20260901_0024_item_origin_occurrence.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260831_0023"' in source
    for table_name in ITEM_ORIGIN_TABLES:
        assert f'"{table_name}"' in source
    assert "DELETE FROM" not in source
    assert "UPDATE items" not in source
    assert "UPDATE item_revisions" not in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "BEFORE INSERT OR UPDATE OR DELETE" in source
    assert "immutable item origin record cannot be changed" in source
    assert "item origin logical identity must start active without a revision" in source
    assert "item origin revision sequence must advance exactly once" in source
    assert "organization current revision pointer is invalid" in source
    assert "assessment occurrence current revision pointer is invalid" in source
    assert "item origin history prevents safe downgrade" in source
    for constraint_name in (
        "fk_assessment_occurrence_organization_revision_identity",
        "fk_item_origin_profile_organization_revision_identity",
        "fk_item_origin_occurrence_revision_identity",
    ):
        assert constraint_name in source
