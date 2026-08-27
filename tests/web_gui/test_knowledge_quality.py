from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from eom_web_gui.contracts import (
    KnowledgeAnalysisBatchRangeStatus,
    KnowledgeAnalysisBatchStatus,
)
from eom_web_gui.gateways import KnowledgeAnalysisRangePage
from eom_web_gui.knowledge_quality import build_knowledge_quality_report
from jsonschema import Draft202012Validator, FormatChecker

from tests.web_gui.helpers import FakeGateway, login, make_client

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
BATCH_ID = "analysisbatch_" + "1" * 32
DOCUMENT_ID = "edudoc_" + "2" * 32
DOCUMENT_REVISION_ID = "edudocrev_" + "3" * 32
VISUAL_SCHEMA = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"


def _batch(
    *, total: int = 2, accepted: int = 1, state: str = "RUNNING"
) -> KnowledgeAnalysisBatchStatus:
    return KnowledgeAnalysisBatchStatus(
        batch_id=BATCH_ID,
        state=state,
        total_range_count=total,
        accepted_range_count=accepted,
        failed_range_count=0,
        failure_code=None,
        resource_version=7,
        created_at=NOW,
        started_at=NOW,
        completed_at=None,
        updated_at=NOW + timedelta(minutes=1),
    )


def _range(
    ordinal: int,
    first_page: int,
    last_page: int,
    *,
    state: str = "PENDING",
    document_revision_id: str = DOCUMENT_REVISION_ID,
    source_revision: str | None = None,
    analysis_revision: str | None = None,
    analysis_run: str | None = None,
    analysis_schema: str = VISUAL_SCHEMA,
    batch_id: str = BATCH_ID,
) -> KnowledgeAnalysisBatchRangeStatus:
    return KnowledgeAnalysisBatchRangeStatus.model_validate(
        {
            "range_id": f"analysisrange_{ordinal + 10:032x}",
            "batch_id": batch_id,
            "ordinal": ordinal,
            "document_id": DOCUMENT_ID,
            "document_revision_id": document_revision_id,
            "first_physical_page": first_page,
            "last_physical_page": last_page,
            "curriculum_unit_keys": ("1-(1)",),
            "source_artifact_revision_id": source_revision or "rev_" + "4" * 32,
            "source_sha256": "sha256:" + "5" * 64,
            "analysis_artifact_revision_id": analysis_revision or f"rev_{ordinal + 20:032x}",
            "analysis_schema_ref": analysis_schema,
            "analysis_run_id": analysis_run,
            "state": state,
            "updated_at": NOW + timedelta(minutes=ordinal + 1),
        }
    )


def test_quality_report_is_deterministic_schema_valid_and_counts_visual_pages() -> None:
    ranges = (
        _range(0, 1, 4, state="ACCEPTED", analysis_run="analysisrun_" + "6" * 32),
        _range(1, 5, 8),
    )
    first = build_knowledge_quality_report(_batch(), reversed(ranges))
    second = build_knowledge_quality_report(_batch(), ranges)

    assert first == second
    assert first.quality_state == "PASS"
    assert first.observed_range_count == 2
    assert first.selected_page_count == first.unique_page_count == 8
    assert first.accepted_page_count == 4
    assert first.in_progress_page_count == 4
    assert first.visual_input_range_count == 2
    assert first.visual_input_page_count == 8
    assert first.gap_page_count == first.overlap_page_count == 0
    assert first.document_count == first.curriculum_unit_count == 1

    schema = json.loads(
        Path("schemas/web-gui/knowledge-analysis-quality-report-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        first.model_dump(mode="json")
    )


def test_quality_report_exposes_gap_without_turning_it_into_content_rejection() -> None:
    report = build_knowledge_quality_report(
        _batch(),
        (_range(0, 1, 2, state="ACCEPTED"), _range(1, 5, 6)),
    )

    assert report.quality_state == "WARN"
    assert report.gap_page_count == 2
    assert [finding.code.value for finding in report.findings] == ["PAGE_COVERAGE_GAP"]


def test_historical_text_only_schema_remains_observable_without_visual_claim() -> None:
    text_schema = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"
    report = build_knowledge_quality_report(
        _batch(total=1),
        (_range(0, 1, 4, state="ACCEPTED", analysis_schema=text_schema),),
    )

    assert report.quality_state == "PASS"
    assert report.visual_input_range_count == 0
    assert report.visual_input_page_count == 0


def test_cancelled_pages_are_not_misreported_as_running() -> None:
    report = build_knowledge_quality_report(
        _batch(total=1, accepted=0, state="CANCELLED"),
        (_range(0, 1, 4, state="CANCELLED"),),
    )

    assert report.cancelled_page_count == 4
    assert report.in_progress_page_count == 0
    assert report.selected_page_count == 4


def test_quality_report_fails_closed_on_overlap_ordinal_and_batch_pointer_drift() -> None:
    report = build_knowledge_quality_report(
        _batch(),
        (
            _range(0, 1, 3, state="ACCEPTED"),
            _range(2, 3, 5, batch_id="analysisbatch_" + "f" * 32),
        ),
    )

    assert report.quality_state == "FAIL"
    assert report.overlap_page_count == 1
    assert {finding.code.value for finding in report.findings} >= {
        "PAGE_COVERAGE_OVERLAP",
        "RANGE_BATCH_POINTER_MISMATCH",
        "RANGE_ORDINAL_SEQUENCE_INVALID",
    }


def test_quality_report_fails_on_duplicate_result_pointers() -> None:
    shared_revision = "rev_" + "a" * 32
    shared_run = "analysisrun_" + "b" * 32
    report = build_knowledge_quality_report(
        _batch(),
        (
            _range(
                0,
                1,
                2,
                state="ACCEPTED",
                analysis_revision=shared_revision,
                analysis_run=shared_run,
            ),
            _range(
                1,
                3,
                4,
                analysis_revision=shared_revision,
                analysis_run=shared_run,
            ),
        ),
    )

    assert report.duplicate_analysis_revision_count == 1
    assert report.duplicate_analysis_run_count == 1
    assert report.quality_state == "FAIL"
    assert {finding.code.value for finding in report.findings} == {
        "ANALYSIS_REVISION_REUSED",
        "ANALYSIS_RUN_REUSED",
    }


def test_quality_report_fails_on_source_pointer_drift() -> None:
    report = build_knowledge_quality_report(
        _batch(),
        (
            _range(0, 1, 2, state="ACCEPTED"),
            _range(1, 3, 4, source_revision="rev_" + "c" * 32),
        ),
    )

    assert report.quality_state == "FAIL"
    assert [finding.code.value for finding in report.findings] == ["SOURCE_POINTER_DRIFT"]


def test_quality_report_handles_the_maximum_linear_page_projection() -> None:
    ranges = tuple(
        _range(
            ordinal,
            1,
            32,
            state="ACCEPTED" if ordinal == 0 else "PENDING",
            document_revision_id=f"edudocrev_{ordinal:032x}",
        )
        for ordinal in range(1000)
    )
    report = build_knowledge_quality_report(_batch(total=1000), ranges)

    assert report.observed_range_count == 1000
    assert report.selected_page_count == 32000
    assert report.unique_page_count == 32000
    assert report.findings == ()


def test_quality_endpoint_fails_closed_on_cursor_cycle() -> None:
    class CyclingGateway(FakeGateway):
        async def knowledge_analysis_batch_ranges(
            self, session: object, batch_id: str, *, cursor: str | None
        ) -> KnowledgeAnalysisRangePage:
            del session, batch_id, cursor
            return KnowledgeAnalysisRangePage(values=(), next_cursor="cycle", has_more=True)

    client, _ = make_client(gateway=CyclingGateway())
    with client:
        login(client)
        response = client.get(
            "/studio/api/v1/admin/knowledge-analysis-batches/analysisbatch_" + "7" * 32 + "/quality"
        )

    assert response.status_code == 502
    assert response.json()["error_code"] == "APPLICATION_API_RESPONSE_INVALID"
