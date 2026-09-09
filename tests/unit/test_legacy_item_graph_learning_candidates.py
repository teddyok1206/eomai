from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
)
from eom_catalog_service.legacy_item_graph_learning_service import (
    LegacyItemGraphLearningService,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, Table, UniqueConstraint, create_engine, text

_BATCH_ID = "legacybatch_" + "1" * 32
_REUSE_BATCH_ID = "legacybatch_" + "3" * 32
_GRAPH_REVISION_ID = "graphrev_" + "2" * 32


def _query_backed_service(
    *, extraction_batch_ids: tuple[str, ...] = (_BATCH_ID,)
) -> tuple[Engine, LegacyItemGraphLearningService]:
    """Build the smallest real relation needed by the candidate selector."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in (
            """
            CREATE TABLE knowledge_analysis_runs (
                analysis_run_id TEXT PRIMARY KEY,
                source_revision_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                canonical_request JSON NOT NULL,
                state TEXT NOT NULL,
                created_by_operator_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE item_revisions (
                item_revision_id TEXT PRIMARY KEY,
                registration_key TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE item_origin_profiles (
                item_origin_profile_id TEXT PRIMARY KEY,
                item_revision_id TEXT NOT NULL UNIQUE
            )
            """,
            """
            CREATE TABLE item_origin_occurrences (
                item_origin_occurrence_id INTEGER PRIMARY KEY,
                item_origin_profile_id TEXT NOT NULL,
                assessment_occurrence_id TEXT NOT NULL,
                assessment_occurrence_revision_id TEXT NOT NULL,
                occurrence_revision_sha256 TEXT NOT NULL,
                UNIQUE (item_origin_profile_id, assessment_occurrence_revision_id)
            )
            """,
            """
            CREATE TABLE item_origin_derivations (
                item_origin_derivation_id INTEGER PRIMARY KEY,
                item_origin_profile_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                logical_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE assessment_occurrence_revisions (
                assessment_occurrence_revision_id TEXT PRIMARY KEY,
                assessment_occurrence_id TEXT NOT NULL,
                revision_sha256 TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                target_school_level TEXT NOT NULL,
                target_grade INTEGER NOT NULL,
                administration_month INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE assessment_source_bundle_revisions (
                assessment_source_bundle_revision_id TEXT PRIMARY KEY,
                assessment_source_bundle_id TEXT NOT NULL,
                assessment_occurrence_id TEXT NOT NULL,
                assessment_occurrence_revision_id TEXT NOT NULL,
                occurrence_revision_sha256 TEXT NOT NULL,
                bundle_manifest_sha256 TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE legacy_item_extraction_decisions (
                acceptance_id TEXT NOT NULL,
                item_proposal_id TEXT NOT NULL,
                item_number INTEGER NOT NULL,
                decision TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE legacy_item_extraction_batch_work_units (
                acceptance_id TEXT NOT NULL,
                extraction_batch_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                assessment_source_bundle_id TEXT NOT NULL,
                assessment_source_bundle_revision_id TEXT NOT NULL,
                bundle_manifest_sha256 TEXT NOT NULL,
                state TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE legacy_item_extraction_batches (
                extraction_batch_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE knowledge_snapshot_analyses (
                graph_snapshot_revision_id TEXT NOT NULL,
                analysis_run_id TEXT NOT NULL,
                UNIQUE (graph_snapshot_revision_id, analysis_run_id)
            )
            """,
        ):
            connection.exec_driver_sql(statement)
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_batches (extraction_batch_id, created_at)
                VALUES (:batch_id, '2026-09-09T00:00:00+00:00')
                """
            ),
            {"batch_id": _BATCH_ID},
        )

    publication = Mock()
    publication.current_structure_context.return_value = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="Integrated science",
        graph_snapshot_revision_id=_GRAPH_REVISION_ID,
        accepted_analysis_run_ids=(),
        structure=cast(Any, object()),
    )
    service = object.__new__(LegacyItemGraphLearningService)
    service.sessions = build_session_factory(engine)
    service.extraction_batch_ids = extraction_batch_ids
    service.publication = publication
    return engine, service


def _insert_candidate(
    engine: Engine,
    *,
    ordinal: int,
    occurrences: tuple[tuple[str, int, int], ...],
) -> str:
    analysis_run_id = f"analysisrun_{ordinal:032x}"
    item_revision_id = f"itemrev_{ordinal:032x}"
    acceptance_id = f"itemacceptance_{ordinal:032x}"
    proposal_id = f"itemproposal_{ordinal:032x}"
    profile_id = f"originprofile_{ordinal:032x}"
    bundle_id = f"assessbundle_{ordinal:032x}"
    bundle_revision_id = f"assessbundlerev_{ordinal:032x}"
    bundle_sha256 = "sha256:" + f"{ordinal + 100:064x}"
    primary_occurrence_id = f"occurrence_{ordinal:032x}"
    primary_occurrence_revision_id = f"occurrev_{ordinal:032x}"
    primary_occurrence_sha256 = "sha256:" + f"{ordinal + 200:064x}"
    request = json.dumps(
        {
            "schema_version": "knowledge-analysis-request/9.0",
            "source": {"source_class": "PAST_EXAM"},
        }
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO item_revisions (item_revision_id, registration_key)
                VALUES (:item_revision_id, :registration_key)
                """
            ),
            {
                "item_revision_id": item_revision_id,
                "registration_key": (f"legacy-item-promotion:{acceptance_id}:{proposal_id}"),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_analysis_runs (
                    analysis_run_id, source_revision_id, source_kind, canonical_request,
                    state, created_by_operator_id, created_at
                ) VALUES (
                    :analysis_run_id, :item_revision_id, 'APPROVED_ITEM_REVISION', :request,
                    'ACCEPTED', :operator_id, :created_at
                )
                """
            ),
            {
                "analysis_run_id": analysis_run_id,
                "item_revision_id": item_revision_id,
                "request": request,
                "operator_id": f"operator-{ordinal}",
                "created_at": f"2026-09-09T00:00:{ordinal:02d}+00:00",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_decisions (
                    acceptance_id, item_proposal_id, item_number, decision
                ) VALUES (:acceptance_id, :proposal_id, :item_number, 'ACCEPT')
                """
            ),
            {
                "acceptance_id": acceptance_id,
                "proposal_id": proposal_id,
                "item_number": ordinal + 1,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_batch_work_units (
                    acceptance_id, extraction_batch_id, ordinal,
                    assessment_source_bundle_id, assessment_source_bundle_revision_id,
                    bundle_manifest_sha256, state
                ) VALUES (
                    :acceptance_id, :batch_id, :ordinal,
                    :bundle_id, :bundle_revision_id, :bundle_sha256, 'ACCEPTED'
                )
                """
            ),
            {
                "acceptance_id": acceptance_id,
                "batch_id": _BATCH_ID,
                "ordinal": ordinal,
                "bundle_id": bundle_id,
                "bundle_revision_id": bundle_revision_id,
                "bundle_sha256": bundle_sha256,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO item_origin_profiles (item_origin_profile_id, item_revision_id)
                VALUES (:profile_id, :item_revision_id)
                """
            ),
            {"profile_id": profile_id, "item_revision_id": item_revision_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO item_origin_derivations (
                    item_origin_profile_id, source_kind, logical_id, revision_id,
                    manifest_sha256
                ) VALUES (
                    :profile_id, 'ASSESSMENT_SOURCE_BUNDLE_REVISION', :bundle_id,
                    :bundle_revision_id, :bundle_sha256
                )
                """
            ),
            {
                "profile_id": profile_id,
                "bundle_id": bundle_id,
                "bundle_revision_id": bundle_revision_id,
                "bundle_sha256": bundle_sha256,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO assessment_source_bundle_revisions (
                    assessment_source_bundle_revision_id, assessment_source_bundle_id,
                    assessment_occurrence_id, assessment_occurrence_revision_id,
                    occurrence_revision_sha256, bundle_manifest_sha256
                ) VALUES (
                    :bundle_revision_id, :bundle_id, :occurrence_id, :occurrence_revision_id,
                    :occurrence_sha256, :bundle_sha256
                )
                """
            ),
            {
                "bundle_revision_id": bundle_revision_id,
                "bundle_id": bundle_id,
                "occurrence_id": primary_occurrence_id,
                "occurrence_revision_id": primary_occurrence_revision_id,
                "occurrence_sha256": primary_occurrence_sha256,
                "bundle_sha256": bundle_sha256,
            },
        )
        for occurrence_index, (school_level, grade, month) in enumerate(occurrences):
            occurrence_id = (
                primary_occurrence_id
                if occurrence_index == 0
                else f"occurrence_{ordinal:016x}{occurrence_index:016x}"
            )
            occurrence_revision_id = (
                primary_occurrence_revision_id
                if occurrence_index == 0
                else f"occurrev_{ordinal:016x}{occurrence_index:016x}"
            )
            occurrence_sha256 = (
                primary_occurrence_sha256
                if occurrence_index == 0
                else "sha256:" + f"{ordinal * 100 + occurrence_index + 300:064x}"
            )
            connection.execute(
                text(
                    """
                    INSERT INTO assessment_occurrence_revisions (
                        assessment_occurrence_revision_id, assessment_occurrence_id,
                        revision_sha256, schema_version,
                        target_school_level, target_grade, administration_month
                    ) VALUES (
                        :revision_id, :occurrence_id, :occurrence_sha256,
                        'assessment-occurrence-revision/2.0',
                        :school_level, :grade, :month
                    )
                    """
                ),
                {
                    "revision_id": occurrence_revision_id,
                    "occurrence_id": occurrence_id,
                    "occurrence_sha256": occurrence_sha256,
                    "school_level": school_level,
                    "grade": grade,
                    "month": month,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO item_origin_occurrences (
                        item_origin_profile_id, assessment_occurrence_id,
                        assessment_occurrence_revision_id, occurrence_revision_sha256
                    ) VALUES (:profile_id, :occurrence_id, :revision_id, :occurrence_sha256)
                    """
                ),
                {
                    "profile_id": profile_id,
                    "occurrence_id": occurrence_id,
                    "revision_id": occurrence_revision_id,
                    "occurrence_sha256": occurrence_sha256,
                },
            )
    return analysis_run_id


def test_pending_candidates_exclude_non_unique_occurrence_placements() -> None:
    engine, service = _query_backed_service()
    first = _insert_candidate(
        engine,
        ordinal=0,
        occurrences=(("HIGH_SCHOOL", 2, 6),),
    )
    _insert_candidate(
        engine,
        ordinal=1,
        occurrences=(("HIGH_SCHOOL", 2, 6), ("HIGH_SCHOOL", 2, 9)),
    )
    _insert_candidate(
        engine,
        ordinal=2,
        occurrences=(("HIGH_SCHOOL", 1, 3), ("HIGH_SCHOOL", 1, 6)),
    )

    candidates = service.pending_candidates(limit=3)

    assert tuple(candidate.analysis_run_id for candidate in candidates) == (first,)
    assert all(
        candidate.graph_snapshot_revision_id == _GRAPH_REVISION_ID for candidate in candidates
    )


def test_pending_candidates_deduplicate_acceptance_reused_by_allowed_batches() -> None:
    engine, service = _query_backed_service(extraction_batch_ids=(_BATCH_ID, _REUSE_BATCH_ID))
    first = _insert_candidate(
        engine,
        ordinal=0,
        occurrences=(("HIGH_SCHOOL", 2, 6),),
    )
    second = _insert_candidate(
        engine,
        ordinal=1,
        occurrences=(("HIGH_SCHOOL", 2, 9),),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_batches (extraction_batch_id, created_at)
                VALUES (:batch_id, '2026-09-10T00:00:00+00:00')
                """
            ),
            {"batch_id": _REUSE_BATCH_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_batch_work_units (
                    acceptance_id, extraction_batch_id, ordinal,
                    assessment_source_bundle_id, assessment_source_bundle_revision_id,
                    bundle_manifest_sha256, state
                ) VALUES (
                    :acceptance_id, :batch_id, 0,
                    :bundle_id, :bundle_revision_id, :bundle_sha256, 'ACCEPTED'
                )
                """
            ),
            {
                "acceptance_id": "itemacceptance_" + f"{0:032x}",
                "batch_id": _REUSE_BATCH_ID,
                "bundle_id": "assessbundle_" + f"{0:032x}",
                "bundle_revision_id": "assessbundlerev_" + f"{0:032x}",
                "bundle_sha256": "sha256:" + f"{100:064x}",
            },
        )

    candidates = service.pending_candidates(limit=2)

    assert tuple(candidate.analysis_run_id for candidate in candidates) == (first, second)


@pytest.mark.parametrize(
    ("mutation_sql", "parameters"),
    (
        (
            """
            UPDATE legacy_item_extraction_batch_work_units
            SET state = 'FAILED'
            WHERE acceptance_id = :acceptance_id
            """,
            {"acceptance_id": "itemacceptance_" + f"{0:032x}"},
        ),
        (
            """
            UPDATE legacy_item_extraction_decisions
            SET decision = 'REJECT'
            WHERE acceptance_id = :acceptance_id
            """,
            {"acceptance_id": "itemacceptance_" + f"{0:032x}"},
        ),
        (
            """
            INSERT INTO item_origin_derivations (
                item_origin_profile_id, source_kind, logical_id, revision_id,
                manifest_sha256
            ) VALUES (
                :profile_id, 'ASSESSMENT_SOURCE_BUNDLE_REVISION', :bundle_id,
                :bundle_revision_id, :bundle_sha256
            )
            """,
            {
                "profile_id": "originprofile_" + f"{0:032x}",
                "bundle_id": "assessbundle_" + "f" * 32,
                "bundle_revision_id": "assessbundlerev_" + "f" * 32,
                "bundle_sha256": "sha256:" + "f" * 64,
            },
        ),
        (
            """
            UPDATE legacy_item_extraction_batch_work_units
            SET bundle_manifest_sha256 = :wrong_hash
            WHERE acceptance_id = :acceptance_id
            """,
            {
                "acceptance_id": "itemacceptance_" + f"{0:032x}",
                "wrong_hash": "sha256:" + "f" * 64,
            },
        ),
    ),
    ids=(
        "work-unit-not-accepted",
        "decision-rejected",
        "duplicate-derivation",
        "bundle-hash-split",
    ),
)
def test_pending_candidates_fail_closed_before_retrieval(
    mutation_sql: str,
    parameters: dict[str, str],
) -> None:
    engine, service = _query_backed_service()
    _insert_candidate(
        engine,
        ordinal=0,
        occurrences=(("HIGH_SCHOOL", 2, 6),),
    )
    with engine.begin() as connection:
        connection.execute(text(mutation_sql), parameters)

    candidates = service.pending_candidates(limit=3)

    assert candidates == ()


def test_candidate_lookup_has_the_required_index_path() -> None:
    # item_revision_id is unique on profiles, the occurrence pair is unique with the profile
    # first, and the occurrence revision is a primary-key lookup.  The correlated EXISTS is
    # therefore an indexed membership check and does not multiply the ordered candidate rows.
    from eom_catalog_service.item_origin_models import (
        AssessmentOccurrenceRevisionRecord,
        ItemOriginDerivationRecord,
        ItemOriginOccurrenceRecord,
        ItemOriginProfileRecord,
    )
    from eom_catalog_service.legacy_assessment_models import (
        AssessmentSourceBundleRevisionRecord,
    )
    from eom_catalog_service.legacy_item_extraction_batch_models import (
        LegacyItemExtractionBatchWorkUnitRecord,
    )

    profile_table = cast(Table, ItemOriginProfileRecord.__table__)
    occurrence_table = cast(Table, ItemOriginOccurrenceRecord.__table__)
    occurrence_revision_table = cast(Table, AssessmentOccurrenceRevisionRecord.__table__)
    derivation_table = cast(Table, ItemOriginDerivationRecord.__table__)
    bundle_revision_table = cast(Table, AssessmentSourceBundleRevisionRecord.__table__)
    work_unit_table = cast(Table, LegacyItemExtractionBatchWorkUnitRecord.__table__)
    profile_indexes = {
        tuple(column.name for column in constraint.columns)
        for constraint in profile_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    occurrence_indexes = {
        tuple(column.name for column in constraint.columns)
        for constraint in occurrence_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    derivation_indexes = {
        tuple(column.name for column in constraint.columns)
        for constraint in derivation_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("item_revision_id",) in profile_indexes
    assert ("item_origin_profile_id", "assessment_occurrence_revision_id") in occurrence_indexes
    assert any(
        columns[:2] == ("item_origin_profile_id", "source_kind") for columns in derivation_indexes
    )
    assert tuple(occurrence_revision_table.primary_key.columns.keys()) == (
        "assessment_occurrence_revision_id",
    )
    assert tuple(bundle_revision_table.primary_key.columns.keys()) == (
        "assessment_source_bundle_revision_id",
    )
    assert any(
        tuple(column.name for column in constraint.columns) == ("extraction_batch_id", "ordinal")
        for constraint in work_unit_table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
