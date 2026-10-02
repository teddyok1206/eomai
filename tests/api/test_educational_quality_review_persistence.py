from __future__ import annotations

import os
from typing import cast

import pytest
from eom_api.educational_quality_models import (
    EducationalQualityReviewObservationRecord,
    EducationalQualityReviewPlanItemRecord,
    EducationalQualityReviewPlanRecord,
    EducationalQualityReviewResolutionRecord,
    EducationalQualityReviewSessionRecord,
)
from eom_orchestrator.database import build_engine
from sqlalchemy import (
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Table,
    UniqueConstraint,
    inspect,
    text,
)

MODELS = (
    EducationalQualityReviewPlanRecord,
    EducationalQualityReviewPlanItemRecord,
    EducationalQualityReviewSessionRecord,
    EducationalQualityReviewObservationRecord,
    EducationalQualityReviewResolutionRecord,
)


def _indexes(table: Table) -> dict[str, Index]:
    return {str(index.name): index for index in table.indexes}


def test_quality_review_persistence_is_pointer_only_and_indexed() -> None:
    for model in MODELS:
        table = cast(Table, model.__table__)
        assert not any(isinstance(column.type, LargeBinary) for column in table.columns)
        assert "content" not in table.columns
        assert "hwpx" not in table.columns

    plan = cast(Table, EducationalQualityReviewPlanRecord.__table__)
    assert set(_indexes(plan)) == {"ix_educational_quality_plan_created"}
    assert {column.name for column in plan.columns if column.name.endswith("sha256")} == {
        "plan_sha256",
        "assembly_manifest_sha256",
        "item_set_sha256",
    }

    plan_item = cast(Table, EducationalQualityReviewPlanItemRecord.__table__)
    assert tuple(column.name for column in plan_item.primary_key.columns) == (
        "plan_id",
        "position",
    )
    assert set(_indexes(plan_item)) == {"ix_educational_quality_plan_item_revision"}

    session = cast(Table, EducationalQualityReviewSessionRecord.__table__)
    constraints = {
        constraint.name
        for constraint in session.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert constraints == {
        "uq_educational_quality_session_independent_reviewer",
        "uq_educational_quality_session_identity_plan",
        "uq_educational_quality_session_plan_role",
    }

    resolution = cast(Table, EducationalQualityReviewResolutionRecord.__table__)
    assert {
        constraint.name
        for constraint in resolution.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    } == {
        "fk_quality_resolution_observation",
        "fk_quality_resolution_session_plan",
        None,
    }


@pytest.mark.integration
@pytest.mark.api_integration
def test_quality_review_migration_matches_authoritative_models() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through the guarded disposable PostgreSQL database")
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    try:
        inspector = inspect(engine)
        for model in MODELS:
            table = cast(Table, model.__table__)
            assert tuple(
                value["name"] for value in inspector.get_columns(table.name, schema="app")
            ) == tuple(table.columns.keys())

        assert {
            (value["name"], tuple(value["column_names"]))
            for value in inspector.get_unique_constraints(
                "educational_quality_review_sessions", schema="app"
            )
        } == {
            (
                "uq_educational_quality_session_independent_reviewer",
                ("plan_id", "reviewer_id"),
            ),
            (
                "uq_educational_quality_session_identity_plan",
                ("session_id", "plan_id"),
            ),
            (
                "uq_educational_quality_session_plan_role",
                ("plan_id", "reviewer_role"),
            ),
        }
        assert {
            (value["name"], tuple(value["constrained_columns"]))
            for value in inspector.get_foreign_keys(
                "educational_quality_review_resolutions", schema="app"
            )
        } >= {
            (
                "fk_quality_resolution_session_plan",
                ("chosen_session_id", "plan_id"),
            ),
            (
                "fk_quality_resolution_observation",
                ("chosen_session_id", "position"),
            ),
        }
        with engine.connect() as connection:
            trigger_names = set(
                connection.execute(
                    text(
                        "SELECT trigger_name FROM information_schema.triggers "
                        "WHERE trigger_schema = 'app' AND event_object_table LIKE "
                        ":table_pattern"
                    ),
                    {"table_pattern": "educational_quality_review_%"},
                ).scalars()
            )
        assert {
            "educational_quality_review_plans_immutable",
            "educational_quality_review_plan_items_immutable",
            "educational_quality_review_resolutions_immutable",
            "educational_quality_session_guard",
            "educational_quality_observation_guard",
        } <= trigger_names
    finally:
        engine.dispose()
