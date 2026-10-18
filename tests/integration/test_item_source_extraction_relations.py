"""Full canonical resolver on guarded pg_temp metadata and exact synthetic members.

The existing owner DB guard is mandatory. No production DB, NAS, auth or model
is used; only the already-tested Artifact metadata seam is synthetic.
"""

from __future__ import annotations

import gc
from collections import Counter

import pytest
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_source_provenance import PastExamSourceResolutionCache
from sqlalchemy import event, insert, select, text, update

from tests.integration.test_inference_transfer_candidate_admission import (
    pool_database as pool_database,
)
from tests.unit.test_item_source_read_relations import relation_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
_LINEAGE_MODELS = (
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionBatchRecord,
    AssessmentSourceBundleRevisionRecord,
    AssessmentLayoutObservationRecord,
)


@pytest.fixture
def extraction_source_database(pool_database, monkeypatch):
    session = pool_database
    fake, reader = relation_case(monkeypatch, 545)
    values = {
        ItemComponentRecord: fake.components,
        LegacyItemExtractionDecisionRecord: fake.decisions,
        LegacyItemExtractionBatchWorkUnitRecord: fake.units,
        **fake.lineage,
    }
    for index, (model, rows) in enumerate(values.items()):
        table = model.__table__
        session.execute(
            text(f"CREATE TEMP TABLE {table.name} AS SELECT * FROM app.{table.name} WITH NO DATA")
        )
        primary = ",".join(column.name for column in table.primary_key)
        session.execute(
            text(
                f"CREATE UNIQUE INDEX extraction_lineage_{index}_pk "
                f"ON pg_temp.{table.name} ({primary})"
            )
        )
        payloads = [
            {key: value for key, value in vars(row).items() if key in table.columns} for row in rows
        ]
        # The source fixture's decision has no persistent key because the unit
        # adapter does not need one. Give the isolated DB row its actual PK.
        if model is LegacyItemExtractionDecisionRecord:
            for number, payload in enumerate(payloads, start=1):
                payload["decision_id"] = number
        elif model is ItemComponentRecord:
            for number, payload in enumerate(payloads, start=1):
                payload["item_component_id"] = f"component_{number:032x}"
        session.execute(insert(table), payloads)
    session.execute(text("TRUNCATE pg_temp.item_revisions"))
    session.execute(
        insert(ItemRevisionRecord),
        [
            {
                key: value
                for key, value in vars(row).items()
                if key in ItemRevisionRecord.__table__.columns
            }
            for row in fake.revisions.values()
        ],
    )
    session.commit()
    return session, reader


def _capture_and_resolve(session, reader, selected):
    cache = PastExamSourceResolutionCache()
    relations = sources.read_item_source_relations(
        session, selected, artifacts=reader, past_exam_cache=cache
    )
    result = tuple(
        sources.resolve_historically_approved_item_source(
            session,
            artifacts=reader,
            item_revision_id=revision,
            source_class="PAST_EXAM",
            past_exam_cache=cache,
            read_relations=relations,
        )
        for revision in selected
    )
    return relations, result


@pytest.mark.parametrize("count", [16, 545])
def test_real_postgres_full_resolver_extraction_queries_are_constant(
    extraction_source_database, count
):
    session, reader = extraction_source_database
    # The real snapshot retains these locked source rows throughout capture.
    revisions = tuple(
        session.scalars(select(ItemRevisionRecord).order_by(ItemRevisionRecord.item_revision_id))
    )
    selected = tuple(row.item_revision_id for row in revisions[:count])
    observed = Counter()

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().startswith("SELECT"):
            for model in _LINEAGE_MODELS:
                if f"FROM {model.__tablename__}" in statement:
                    observed[model.__tablename__] += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        captures = []
        for _ in range(4):
            gc.collect()
            relations, result = _capture_and_resolve(session, reader, selected)
            assert len(result) == count
            captures.append(relations)
        assert all(observed[model.__tablename__] == 4 for model in _LINEAGE_MODELS)
        assert len({id(value) for value in captures}) == 4
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.mark.parametrize("model", _LINEAGE_MODELS)
def test_real_postgres_fresh_capture_rejects_deleted_extraction_dependency(
    extraction_source_database, model
):
    session, reader = extraction_source_database
    selected = tuple(session.scalars(select(ItemRevisionRecord.item_revision_id).limit(1)))
    _capture_and_resolve(session, reader, selected)
    session.execute(model.__table__.delete())
    session.commit()
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        _capture_and_resolve(session, reader, selected)


def test_real_postgres_fresh_capture_refreshes_held_bundle_and_acceptance(
    extraction_source_database,
):
    session, reader = extraction_source_database
    selected = tuple(session.scalars(select(ItemRevisionRecord.item_revision_id).limit(1)))
    first, _ = _capture_and_resolve(session, reader, selected)
    bundle = next(iter(first._bundles.values()))
    acceptance = next(iter(first._acceptances.values()))
    session.execute(
        update(AssessmentSourceBundleRevisionRecord)
        .values(state="DRAFT")
        .execution_options(synchronize_session=False)
    )
    session.execute(
        update(LegacyItemExtractionAcceptanceRecord)
        .values(coverage_state="INCOMPLETE")
        .execution_options(synchronize_session=False)
    )
    assert bundle.state == "REVIEWED" and acceptance.coverage_state == "COMPLETE"
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        _capture_and_resolve(session, reader, selected)
    assert bundle.state == "DRAFT" and acceptance.coverage_state == "INCOMPLETE"


def test_real_postgres_canonical_output_matches_standalone_and_lineage_pk_plans(
    extraction_source_database,
):
    session, reader = extraction_source_database
    selected = tuple(
        session.scalars(
            select(ItemRevisionRecord.item_revision_id)
            .order_by(ItemRevisionRecord.item_revision_id)
            .limit(16)
        )
    )
    original_scalars = session.scalars
    statements = []

    def record(statement, *args, **kwargs):
        statements.append(statement)
        return original_scalars(statement, *args, **kwargs)

    session.scalars = record
    try:
        _relations, result = _capture_and_resolve(session, reader, selected)
    finally:
        session.scalars = original_scalars
    legacy_cache = PastExamSourceResolutionCache()
    legacy = tuple(
        sources.resolve_historically_approved_item_source(
            session,
            artifacts=reader,
            item_revision_id=revision,
            source_class="PAST_EXAM",
            past_exam_cache=legacy_cache,
        )
        for revision in selected
    )
    assert result == legacy
    session.execute(text("SET LOCAL enable_seqscan=off"))
    lineage_queries = [
        statement
        for statement in statements
        if statement.column_descriptions[0]["entity"] in _LINEAGE_MODELS
    ]
    assert len(lineage_queries) == 4
    for statement in lineage_queries:
        assert statement.get_execution_options()["populate_existing"]
        compiled = statement.compile(
            dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True}
        )
        assert " IN (" in str(compiled)  # selected exact IDs, not a layout/bundle scan
        plan = "\n".join(session.scalars(text("EXPLAIN (COSTS OFF) " + str(compiled))))
        assert "extraction_lineage_" in plan and "_pk" in plan
