from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisRequestV9,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_graph_learning_service import (
    LegacyItemGraphLearningError,
    LegacyItemGraphLearningService,
)
from eom_catalog_service.past_exam_origin_resolution import (
    PastExamOriginInput,
    PastExamOriginResolution,
    PastExamOriginResolutionError,
    PastExamOriginStatus,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, Table, UniqueConstraint, create_engine, text

_BATCH_ID = "legacybatch_" + "1" * 32
_REUSE_BATCH_ID = "legacybatch_" + "3" * 32
_GRAPH_REVISION_ID = "graphrev_" + "2" * 32


def _hash(seed: int) -> str:
    return "sha256:" + f"{seed:064x}"


def _source_from_json(value: dict[str, Any]) -> ApprovedPastExamItemKnowledgeSourceV3:
    source = value["source"]
    if (
        value.get("invalid")
        or value.get("schema_version") != PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION
        or source.get("source_class") != "PAST_EXAM"
        or not source.get("extraction_acceptance_id")
    ):
        raise ValueError("synthetic invalid in-scope request")
    pointer = SimpleNamespace(
        artifact_id="artifact",
        artifact_revision_id="revision",
        member_path="member.json",
        schema_ref="schema/1.0",
        media_type="application/json",
        sha256=source["artifact_sha256"],
    )
    return ApprovedPastExamItemKnowledgeSourceV3.model_construct(
        item_id=source["item_id"],
        item_revision_id=source["item_revision_id"],
        extraction_acceptance_id=source["extraction_acceptance_id"],
        extraction_acceptance_sha256=source["extraction_acceptance_sha256"],
        extraction_acceptance_artifact=pointer,
        extraction_result_id=source["extraction_result_id"],
        extraction_result_sha256=source["extraction_result_sha256"],
        extraction_result_artifact=pointer,
        item_proposal_id=source["item_proposal_id"],
        item_number=source["item_number"],
        bundle=SimpleNamespace(
            assessment_source_bundle_id=source["assessment_source_bundle_id"],
            assessment_source_bundle_revision_id=source["assessment_source_bundle_revision_id"],
            bundle_manifest_sha256=source["bundle_manifest_sha256"],
        ),
    )


@pytest.fixture(autouse=True)
def _parse_synthetic_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        KnowledgeAnalysisRequestV9,
        "model_validate",
        classmethod(lambda _cls, value: SimpleNamespace(source=_source_from_json(value))),
    )


def _resolution(
    origin: PastExamOriginInput,
    *,
    status: PastExamOriginStatus = PastExamOriginStatus.ELIGIBLE,
) -> PastExamOriginResolution:
    source = origin.source
    return PastExamOriginResolution(
        analysis_run_id=origin.analysis_run_id,
        item_id=source.item_id,
        item_revision_id=source.item_revision_id,
        item_origin_profile_id="profile-" + source.item_revision_id,
        item_origin_profile_sha256=_hash(900_001),
        extraction_acceptance_id=source.extraction_acceptance_id,
        extraction_acceptance_sha256=source.extraction_acceptance_sha256,
        assessment_source_bundle_id=source.bundle.assessment_source_bundle_id,
        assessment_source_bundle_revision_id=source.bundle.assessment_source_bundle_revision_id,
        assessment_source_bundle_sha256=source.bundle.bundle_manifest_sha256,
        assessment_occurrence_id="occurrence",
        assessment_occurrence_revision_id="occurrence-revision",
        assessment_occurrence_revision_sha256=_hash(900_002),
        occurrence_display_label="Synthetic occurrence",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=2,
        subject_key="integrated-science",
        item_number=source.item_number,
        status=status,
    )


def _query_backed_service(
    *, extraction_batch_ids: tuple[str, ...] = (_BATCH_ID,)
) -> tuple[Engine, LegacyItemGraphLearningService]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in (
            """
            CREATE TABLE knowledge_analysis_runs (
                analysis_run_id TEXT PRIMARY KEY,
                source_revision_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                item_id TEXT,
                item_revision_id TEXT,
                canonical_request JSON NOT NULL,
                state TEXT NOT NULL,
                created_by_operator_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE legacy_item_extraction_batch_work_units (
                work_unit_id TEXT PRIMARY KEY,
                acceptance_id TEXT,
                acceptance_sha256 TEXT,
                extraction_result_id TEXT,
                result_sha256 TEXT,
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
            CREATE TABLE legacy_item_extraction_decisions (
                acceptance_id TEXT NOT NULL,
                item_proposal_id TEXT NOT NULL,
                UNIQUE (acceptance_id, item_proposal_id)
            )
            """,
            """
            CREATE TABLE item_revisions (
                item_revision_id TEXT PRIMARY KEY,
                registration_key TEXT NOT NULL UNIQUE
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
    service.retrieval = Mock()
    service._resolve_past_exam_origins = Mock(  # type: ignore[method-assign]
        side_effect=lambda _session, inputs: tuple(_resolution(origin) for origin in inputs)
    )
    return engine, service


def _source_value(ordinal: int) -> dict[str, Any]:
    return {
        "source_class": "PAST_EXAM",
        "item_id": f"item_{ordinal}",
        "item_revision_id": f"itemrev_{ordinal}",
        "extraction_acceptance_id": f"itemacceptance_{ordinal}",
        "extraction_acceptance_sha256": _hash(ordinal + 100),
        "extraction_result_id": f"itemextractresult_{ordinal}",
        "extraction_result_sha256": _hash(ordinal + 200),
        "item_proposal_id": f"itemproposal_{ordinal}",
        "item_number": ordinal + 1,
        "assessment_source_bundle_id": f"assessbundle_{ordinal}",
        "assessment_source_bundle_revision_id": f"assessbundlerev_{ordinal}",
        "bundle_manifest_sha256": _hash(ordinal + 300),
        "artifact_sha256": _hash(ordinal + 400),
    }


def _insert_membership(
    engine: Engine,
    *,
    ordinal: int,
    source: dict[str, Any],
    batch_id: str = _BATCH_ID,
    state: str = "ACCEPTED",
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT OR IGNORE INTO legacy_item_extraction_decisions (
                    acceptance_id, item_proposal_id
                ) VALUES (:acceptance_id, :item_proposal_id)
                """
            ),
            {
                "acceptance_id": source["extraction_acceptance_id"],
                "item_proposal_id": source["item_proposal_id"],
            },
        )
        connection.execute(
            text(
                """
                INSERT OR IGNORE INTO item_revisions (item_revision_id, registration_key)
                VALUES (:item_revision_id, :registration_key)
                """
            ),
            {
                "item_revision_id": source["item_revision_id"],
                "registration_key": (
                    "legacy-item-promotion:"
                    f"{source['extraction_acceptance_id']}:{source['item_proposal_id']}"
                ),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO legacy_item_extraction_batch_work_units (
                    work_unit_id, acceptance_id, acceptance_sha256, extraction_result_id,
                    result_sha256, extraction_batch_id, ordinal,
                    assessment_source_bundle_id, assessment_source_bundle_revision_id,
                    bundle_manifest_sha256, state
                ) VALUES (
                    :work_unit_id, :acceptance_id, :acceptance_sha256, :extraction_result_id,
                    :result_sha256, :batch_id, :ordinal, :bundle_id, :bundle_revision_id,
                    :bundle_sha256, :state
                )
                """
            ),
            {
                "work_unit_id": f"workunit-{batch_id}-{ordinal}",
                "acceptance_id": source["extraction_acceptance_id"],
                "acceptance_sha256": source["extraction_acceptance_sha256"],
                "extraction_result_id": source["extraction_result_id"],
                "result_sha256": source["extraction_result_sha256"],
                "batch_id": batch_id,
                "ordinal": ordinal,
                "bundle_id": source["assessment_source_bundle_id"],
                "bundle_revision_id": source["assessment_source_bundle_revision_id"],
                "bundle_sha256": source["bundle_manifest_sha256"],
                "state": state,
            },
        )


def _insert_analysis(
    engine: Engine,
    *,
    ordinal: int,
    source: dict[str, Any],
    invalid_request: bool = False,
    source_revision_id: str | None = None,
    schema_version: str = PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
    source_class: str = "PAST_EXAM",
) -> str:
    analysis_run_id = f"analysisrun_{ordinal}"
    request_source = dict(source)
    request_source["source_class"] = source_class
    request = {
        "schema_version": schema_version,
        "source": request_source,
        "invalid": invalid_request,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO knowledge_analysis_runs (
                    analysis_run_id, source_revision_id, source_kind, item_id, item_revision_id,
                    canonical_request,
                    state, created_by_operator_id, created_at
                ) VALUES (
                    :analysis_run_id, :source_revision_id, 'APPROVED_ITEM_REVISION', :item_id,
                    :item_revision_id, :request,
                    'ACCEPTED', :operator_id, :created_at
                )
                """
            ),
            {
                "analysis_run_id": analysis_run_id,
                "source_revision_id": source_revision_id or source["item_revision_id"],
                "item_id": source["item_id"],
                "item_revision_id": source["item_revision_id"],
                "request": json.dumps(request),
                "operator_id": f"operator-{ordinal}",
                "created_at": f"2026-09-09T00:{ordinal // 60:02d}:{ordinal % 60:02d}+00:00",
            },
        )
    return analysis_run_id


def _insert_candidate(
    engine: Engine,
    *,
    ordinal: int,
    state: str = "ACCEPTED",
) -> tuple[str, dict[str, Any]]:
    source = _source_value(ordinal)
    _insert_membership(engine, ordinal=ordinal, source=source, state=state)
    return _insert_analysis(engine, ordinal=ordinal, source=source), source


def test_policy_excluded_rows_do_not_consume_limit_and_all_rows_are_classified() -> None:
    engine, service = _query_backed_service()
    first, _ = _insert_candidate(engine, ordinal=0)
    second, _ = _insert_candidate(engine, ordinal=1)
    third, _ = _insert_candidate(engine, ordinal=2)

    def classify(_session: Any, inputs: tuple[PastExamOriginInput, ...]) -> Any:
        assert tuple(origin.analysis_run_id for origin in inputs) == (first, second, third)
        return tuple(
            _resolution(
                origin,
                status=(
                    PastExamOriginStatus.POLICY_EXCLUDED
                    if origin.analysis_run_id == first
                    else PastExamOriginStatus.ELIGIBLE
                ),
            )
            for origin in inputs
        )

    service._resolve_past_exam_origins = Mock(side_effect=classify)  # type: ignore[method-assign]

    candidates = service.pending_candidates(limit=1)

    assert tuple(candidate.analysis_run_id for candidate in candidates) == (second,)


def test_acceptance_reused_by_allowed_batches_is_validated_once_and_not_duplicated() -> None:
    engine, service = _query_backed_service(extraction_batch_ids=(_BATCH_ID, _REUSE_BATCH_ID))
    first, source = _insert_candidate(engine, ordinal=0)
    second, _ = _insert_candidate(engine, ordinal=1)
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
    _insert_membership(engine, ordinal=0, source=source, batch_id=_REUSE_BATCH_ID)

    candidates = service.pending_candidates(limit=2)

    assert tuple(candidate.analysis_run_id for candidate in candidates) == (first, second)
    resolver_inputs = service._resolve_past_exam_origins.call_args.args[1]
    assert tuple(origin.analysis_run_id for origin in resolver_inputs) == (first, second)


@pytest.mark.parametrize(
    "mutation",
    (
        "state",
        "acceptance-hash",
        "source-kind",
        "source-revision",
        "item-id",
        "item-revision",
    ),
)
def test_in_scope_membership_or_source_pointer_drift_is_an_explicit_error(mutation: str) -> None:
    engine, service = _query_backed_service()
    analysis_run_id, source = _insert_candidate(engine, ordinal=0)
    with engine.begin() as connection:
        if mutation == "state":
            connection.execute(
                text("UPDATE legacy_item_extraction_batch_work_units SET state='FAILED'")
            )
        elif mutation == "acceptance-hash":
            connection.execute(
                text("UPDATE legacy_item_extraction_batch_work_units SET acceptance_sha256=:value"),
                {"value": _hash(999_001)},
            )
        else:
            field = {
                "source-kind": "source_kind",
                "source-revision": "source_revision_id",
                "item-id": "item_id",
                "item-revision": "item_revision_id",
            }[mutation]
            connection.execute(text(f"UPDATE knowledge_analysis_runs SET {field}='wrong'"))

    with pytest.raises(LegacyItemGraphLearningError) as caught:
        service.pending_candidates(limit=1)

    assert caught.value.code == "LEGACY_ITEM_GRAPH_ORIGIN_INVALID"
    assert caught.value.reason == "batch_membership_or_decision_invalid"
    assert caught.value.analysis_run_id == analysis_run_id
    assert caught.value.item_revision_id == source["item_revision_id"]
    service.retrieval.create.assert_not_called()


def test_in_scope_malformed_request_errors_but_out_of_scope_malformed_request_is_ignored() -> None:
    engine, service = _query_backed_service()
    valid_id, _ = _insert_candidate(engine, ordinal=0)
    outside = _source_value(1)
    _insert_analysis(engine, ordinal=1, source=outside, invalid_request=True)

    assert tuple(
        candidate.analysis_run_id for candidate in service.pending_candidates(limit=2)
    ) == (valid_id,)

    inside = _source_value(2)
    _insert_membership(engine, ordinal=2, source=inside)
    _insert_analysis(engine, ordinal=2, source=inside, invalid_request=True)
    with pytest.raises(LegacyItemGraphLearningError) as caught:
        service.pending_candidates(limit=2)

    assert caught.value.reason == "canonical_request_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "knowledge-analysis-request/8.0"),
        ("source_class", "EDUCATIONAL_DOCUMENT"),
    ),
)
def test_in_scope_request_discriminator_drift_is_an_explicit_error(field: str, value: str) -> None:
    engine, service = _query_backed_service()
    source = _source_value(0)
    _insert_membership(engine, ordinal=0, source=source)
    analysis_run_id = _insert_analysis(
        engine,
        ordinal=0,
        source=source,
        schema_version=(
            value if field == "schema_version" else PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION
        ),
        source_class=value if field == "source_class" else "PAST_EXAM",
    )

    with pytest.raises(LegacyItemGraphLearningError) as caught:
        service.pending_candidates(limit=1)

    assert caught.value.reason == "canonical_request_invalid"
    assert caught.value.analysis_run_id == analysis_run_id
    assert caught.value.item_revision_id == "unknown"
    service._resolve_past_exam_origins.assert_not_called()
    service.retrieval.create.assert_not_called()


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        ("drift", "batch_membership_or_decision_invalid"),
        ("missing", "canonical_request_invalid"),
    ),
)
def test_relational_promotion_scope_catches_acceptance_id_drift_or_absence(
    mutation: str, expected_reason: str
) -> None:
    engine, service = _query_backed_service()
    analysis_run_id, source = _insert_candidate(engine, ordinal=0)
    with engine.begin() as connection:
        request = connection.execute(
            text(
                "SELECT canonical_request FROM knowledge_analysis_runs "
                "WHERE analysis_run_id=:analysis_run_id"
            ),
            {"analysis_run_id": analysis_run_id},
        ).scalar_one()
        value = json.loads(request)
        if mutation == "drift":
            value["source"]["extraction_acceptance_id"] = "itemacceptance_" + "f" * 32
        else:
            value["source"].pop("extraction_acceptance_id")
        connection.execute(
            text(
                "UPDATE knowledge_analysis_runs SET canonical_request=:request "
                "WHERE analysis_run_id=:analysis_run_id"
            ),
            {"analysis_run_id": analysis_run_id, "request": json.dumps(value)},
        )

    with pytest.raises(LegacyItemGraphLearningError) as caught:
        service.pending_candidates(limit=1)

    assert caught.value.reason == expected_reason
    assert caught.value.analysis_run_id == analysis_run_id
    assert caught.value.item_revision_id == (
        "unknown" if mutation == "missing" else source["item_revision_id"]
    )
    service._resolve_past_exam_origins.assert_not_called()
    service.retrieval.create.assert_not_called()


def test_no_allowlisted_membership_is_a_legitimate_out_of_scope_analysis() -> None:
    engine, service = _query_backed_service()
    source = _source_value(0)
    _insert_analysis(engine, ordinal=0, source=source)

    assert service.pending_candidates(limit=1) == ()
    service._resolve_past_exam_origins.assert_not_called()


def test_invalid_row_after_output_limit_still_fails_before_retrieval() -> None:
    engine, service = _query_backed_service()
    analysis_ids = tuple(_insert_candidate(engine, ordinal=value)[0] for value in range(17))

    def reject_tail(_session: Any, inputs: tuple[PastExamOriginInput, ...]) -> Any:
        assert tuple(origin.analysis_run_id for origin in inputs) == analysis_ids
        tail = inputs[-1]
        raise PastExamOriginResolutionError(
            analysis_run_id=tail.analysis_run_id,
            item_revision_id=tail.source.item_revision_id,
            reason="origin_occurrence_cardinality",
        )

    # Exercise the real boundary translation rather than replacing its wrapper.
    service._resolve_past_exam_origins = LegacyItemGraphLearningService.__dict__[  # type: ignore[method-assign]
        "_resolve_past_exam_origins"
    ].__get__(service, LegacyItemGraphLearningService)
    import eom_catalog_service.legacy_item_graph_learning_service as module

    original = module.resolve_past_exam_origins
    module.resolve_past_exam_origins = reject_tail
    try:
        with pytest.raises(LegacyItemGraphLearningError) as caught:
            service.pending_candidates(limit=1)
    finally:
        module.resolve_past_exam_origins = original

    assert caught.value.analysis_run_id == analysis_ids[-1]
    assert caught.value.reason == "origin_occurrence_cardinality"
    service.retrieval.create.assert_not_called()


def test_candidate_membership_lookup_has_stable_unique_order_index() -> None:
    work_unit_table = cast(Table, LegacyItemExtractionBatchWorkUnitRecord.__table__)

    assert any(
        tuple(column.name for column in constraint.columns) == ("extraction_batch_id", "ordinal")
        for constraint in work_unit_table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
