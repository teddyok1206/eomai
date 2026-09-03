from __future__ import annotations

from pathlib import Path

import eom_catalog_service.legacy_item_learning_models as _legacy_item_learning_models  # noqa: F401
from eom_orchestrator.models import Base
from sqlalchemy import LargeBinary

TABLES = {
    "legacy_item_editorial_compatibility_policy_revisions",
    "legacy_item_editorial_compatibility_runs",
    "legacy_item_editorial_compatibility_events",
}


def _foreign_key_targets(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in Base.metadata.tables[table_name].foreign_key_constraints
    }


def _foreign_key_target_list(table_name: str) -> list[tuple[str, ...]]:
    return [
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in Base.metadata.tables[table_name].foreign_key_constraints
    ]


def test_editorial_compatibility_metadata_is_pointer_oriented_and_indexed() -> None:
    assert set(Base.metadata.tables) >= TABLES
    for table_name in TABLES:
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)

    run = Base.metadata.tables["legacy_item_editorial_compatibility_runs"]
    assert {
        "item_revision_id",
        "item_content_artifact_revision_id",
        "authoring_prompt_artifact_revision_id",
        "hwpx_profile_artifact_revision_id",
        "renderer_profile_artifact_revision_id",
        "proposal_artifact_revision_id",
        "result_artifact_revision_id",
    } <= set(run.columns.keys())
    assert {
        "ix_legacy_editorial_compatibility_item_history",
        "ix_legacy_editorial_compatibility_authorities",
        "ix_legacy_editorial_compatibility_open_work",
        "uq_legacy_editorial_compatibility_active_tuple",
        "uq_legacy_editorial_compatibility_terminal_tuple",
    } <= {str(index.name) for index in run.indexes}


def test_editorial_compatibility_metadata_closes_composite_revision_pointers() -> None:
    run_table = "legacy_item_editorial_compatibility_runs"
    targets = _foreign_key_targets(run_table)
    assert (
        "item_revisions.item_id",
        "item_revisions.item_revision_id",
    ) in targets
    artifact_revision = (
        "artifact_revisions.logical_artifact_id",
        "artifact_revisions.revision_id",
    )
    assert (
        len(
            [
                target
                for target in _foreign_key_target_list(run_table)
                if target == artifact_revision
            ]
        )
        == 6
    )


def test_editorial_compatibility_migration_is_additive_immutable_and_indexed() -> None:
    source = Path(
        "migrations/versions/20260903_0026_legacy_item_editorial_compatibility.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260901_0025"' in source
    for table_name in TABLES:
        assert f'"{table_name}"' in source
    assert "DELETE FROM" not in source
    assert "UPDATE item_revisions" not in source
    assert "BEFORE UPDATE OR DELETE" in source
    for protected_name in (
        "uq_legacy_editorial_compatibility_terminal_tuple",
        "uq_legacy_editorial_compatibility_active_tuple",
        "uq_legacy_editorial_compatibility_predecessor",
        "ix_legacy_editorial_compatibility_item_history",
        "ix_legacy_editorial_compatibility_authorities",
        "ix_legacy_editorial_compatibility_open_work",
        "fk_legacy_editorial_compatibility_item_revision_identity",
        "fk_legacy_editorial_compatibility_proposal_identity",
        "fk_legacy_editorial_compatibility_result_identity",
        "fk_legacy_editorial_compatibility_renderer_identity",
        "ck_legacy_editorial_compatibility_proposal_pointer_complete",
        "ck_legacy_editorial_compatibility_result_pointer_complete",
    ):
        assert protected_name in source


def test_editorial_compatibility_metadata_has_no_large_payload_columns() -> None:
    run = Base.metadata.tables["legacy_item_editorial_compatibility_runs"]
    forbidden = {"bytes", "image", "markdown", "pdf", "prompt", "result", "nas_path"}
    assert forbidden.isdisjoint(run.columns.keys())
