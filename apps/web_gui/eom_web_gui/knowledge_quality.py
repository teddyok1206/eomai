"""Pure, deterministic quality observation over Knowledge Analysis range projections."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Literal

from eom_web_gui.contracts import (
    KnowledgeAnalysisBatchRangeStatus,
    KnowledgeAnalysisBatchStatus,
    KnowledgeAnalysisQualityReport,
    KnowledgeDocumentCoverage,
    KnowledgeQualityFinding,
    KnowledgeQualityFindingCode,
)

_VISUAL_SCHEMA = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
_IN_PROGRESS_STATES = frozenset({"PENDING", "CLAIMED", "SUBMITTED"})
_FindingSeverity = Literal["WARNING", "ERROR"]
_QualityState = Literal["PASS", "WARN", "FAIL"]


def build_knowledge_quality_report(
    batch: KnowledgeAnalysisBatchStatus,
    ranges: Iterable[KnowledgeAnalysisBatchRangeStatus],
) -> KnowledgeAnalysisQualityReport:
    """Build an ephemeral O(r log r + p) report without mutating source projections."""

    ordered = tuple(sorted(ranges, key=lambda value: (value.ordinal, value.range_id)))
    findings: list[KnowledgeQualityFinding] = []
    observed_at = max((value.updated_at for value in ordered), default=batch.updated_at)
    observed_at = max(observed_at, batch.updated_at)

    if len(ordered) != batch.total_range_count:
        findings.append(
            _finding(KnowledgeQualityFindingCode.BATCH_RANGE_COUNT_MISMATCH, "ERROR", ordered)
        )
    mismatched_batch = tuple(value for value in ordered if value.batch_id != batch.batch_id)
    if mismatched_batch:
        findings.append(
            _finding(
                KnowledgeQualityFindingCode.RANGE_BATCH_POINTER_MISMATCH,
                "ERROR",
                mismatched_batch,
            )
        )
    if tuple(value.ordinal for value in ordered) != tuple(range(len(ordered))):
        findings.append(
            _finding(
                KnowledgeQualityFindingCode.RANGE_ORDINAL_SEQUENCE_INVALID,
                "ERROR",
                ordered,
            )
        )

    _append_duplicate_pointer_findings(
        findings,
        ordered,
        code=KnowledgeQualityFindingCode.ANALYSIS_REVISION_REUSED,
        pointers=(value.analysis_artifact_revision_id for value in ordered),
    )
    _append_duplicate_pointer_findings(
        findings,
        ordered,
        code=KnowledgeQualityFindingCode.ANALYSIS_RUN_REUSED,
        pointers=(value.analysis_run_id for value in ordered),
    )

    by_document: dict[str, list[KnowledgeAnalysisBatchRangeStatus]] = defaultdict(list)
    for value in ordered:
        by_document[value.document_revision_id].append(value)

    documents: list[KnowledgeDocumentCoverage] = []
    curriculum_unit_keys: set[str] = set()
    selected_page_count = 0
    accepted_page_count = 0
    failed_page_count = 0
    cancelled_page_count = 0
    in_progress_page_count = 0
    visual_input_range_count = 0
    visual_input_page_count = 0
    gap_page_count = 0
    overlap_page_count = 0

    for document_revision_id in sorted(by_document):
        document_ranges = tuple(
            sorted(
                by_document[document_revision_id],
                key=lambda value: (
                    value.first_physical_page,
                    value.last_physical_page,
                    value.ordinal,
                ),
            )
        )
        page_occurrences: Counter[int] = Counter()
        document_selected = 0
        document_accepted = 0
        document_failed = 0
        document_cancelled = 0
        document_in_progress = 0
        document_curriculum_keys: set[str] = set()
        for value in document_ranges:
            length = value.last_physical_page - value.first_physical_page + 1
            pages = range(value.first_physical_page, value.last_physical_page + 1)
            page_occurrences.update(pages)
            document_selected += length
            if value.state == "ACCEPTED":
                document_accepted += length
            elif value.state == "FAILED":
                document_failed += length
            elif value.state == "CANCELLED":
                document_cancelled += length
            elif value.state in _IN_PROGRESS_STATES:
                document_in_progress += length
            else:  # pragma: no cover - the frozen range model closes this branch
                raise AssertionError("unhandled analysis range state")
            if value.analysis_schema_ref == _VISUAL_SCHEMA:
                visual_input_range_count += 1
                visual_input_page_count += length
            document_curriculum_keys.update(value.curriculum_unit_keys)

        first_page = min(page_occurrences)
        last_page = max(page_occurrences)
        gaps = tuple(
            page for page in range(first_page, last_page + 1) if page not in page_occurrences
        )
        overlaps = tuple(page for page, count in page_occurrences.items() if count > 1)
        if gaps:
            findings.append(
                KnowledgeQualityFinding(
                    code=KnowledgeQualityFindingCode.PAGE_COVERAGE_GAP,
                    severity="WARNING",
                    document_revision_id=document_revision_id,
                    first_physical_page=min(gaps),
                    last_physical_page=max(gaps),
                    range_ids=(),
                )
            )
        if overlaps:
            overlapping_ranges = tuple(
                value
                for value in document_ranges
                if any(
                    value.first_physical_page <= page <= value.last_physical_page
                    for page in overlaps
                )
            )
            findings.append(
                KnowledgeQualityFinding(
                    code=KnowledgeQualityFindingCode.PAGE_COVERAGE_OVERLAP,
                    severity="ERROR",
                    document_revision_id=document_revision_id,
                    first_physical_page=min(overlaps),
                    last_physical_page=max(overlaps),
                    range_ids=_range_ids(overlapping_ranges),
                )
            )

        source_identities = {
            (
                value.document_id,
                value.source_artifact_revision_id,
                value.source_sha256,
            )
            for value in document_ranges
        }
        if len(source_identities) != 1:
            findings.append(
                _finding(
                    KnowledgeQualityFindingCode.SOURCE_POINTER_DRIFT,
                    "ERROR",
                    document_ranges,
                    document_revision_id=document_revision_id,
                )
            )
        canonical = document_ranges[0]
        documents.append(
            KnowledgeDocumentCoverage(
                document_id=canonical.document_id,
                document_revision_id=document_revision_id,
                source_artifact_revision_id=canonical.source_artifact_revision_id,
                source_sha256=canonical.source_sha256,
                first_physical_page=first_page,
                last_physical_page=last_page,
                range_count=len(document_ranges),
                unique_page_count=len(page_occurrences),
                accepted_page_count=document_accepted,
                cancelled_page_count=document_cancelled,
                failed_page_count=document_failed,
                in_progress_page_count=document_in_progress,
                gap_page_count=len(gaps),
                overlap_page_count=len(overlaps),
                curriculum_unit_keys=tuple(sorted(document_curriculum_keys)),
            )
        )
        curriculum_unit_keys.update(document_curriculum_keys)
        selected_page_count += document_selected
        accepted_page_count += document_accepted
        failed_page_count += document_failed
        cancelled_page_count += document_cancelled
        in_progress_page_count += document_in_progress
        gap_page_count += len(gaps)
        overlap_page_count += len(overlaps)

    findings.sort(key=_finding_sort_key)
    severities = {finding.severity for finding in findings}
    quality_state: _QualityState = (
        "FAIL" if "ERROR" in severities else "WARN" if severities else "PASS"
    )
    return KnowledgeAnalysisQualityReport(
        batch_id=batch.batch_id,
        resource_version=batch.resource_version,
        quality_state=quality_state,
        total_range_count=batch.total_range_count,
        observed_range_count=len(ordered),
        selected_page_count=selected_page_count,
        unique_page_count=sum(value.unique_page_count for value in documents),
        accepted_page_count=accepted_page_count,
        cancelled_page_count=cancelled_page_count,
        failed_page_count=failed_page_count,
        in_progress_page_count=in_progress_page_count,
        visual_input_range_count=visual_input_range_count,
        visual_input_page_count=visual_input_page_count,
        gap_page_count=gap_page_count,
        overlap_page_count=overlap_page_count,
        duplicate_analysis_revision_count=_duplicate_pointer_count(
            value.analysis_artifact_revision_id for value in ordered
        ),
        duplicate_analysis_run_count=_duplicate_pointer_count(
            value.analysis_run_id for value in ordered
        ),
        document_count=len(documents),
        curriculum_unit_count=len(curriculum_unit_keys),
        documents=tuple(documents),
        findings=tuple(findings),
        observed_at=observed_at,
    )


def _append_duplicate_pointer_findings(
    findings: list[KnowledgeQualityFinding],
    ranges: tuple[KnowledgeAnalysisBatchRangeStatus, ...],
    *,
    code: KnowledgeQualityFindingCode,
    pointers: Iterable[str | None],
) -> None:
    by_pointer: dict[str, list[KnowledgeAnalysisBatchRangeStatus]] = defaultdict(list)
    for value, pointer in zip(ranges, pointers, strict=True):
        if pointer is not None:
            by_pointer[pointer].append(value)
    for pointer in sorted(by_pointer):
        matching = tuple(by_pointer[pointer])
        if len(matching) > 1:
            findings.append(_finding(code, "ERROR", matching))


def _duplicate_pointer_count(pointers: Iterable[str | None]) -> int:
    counts = Counter(pointer for pointer in pointers if pointer is not None)
    return sum(1 for count in counts.values() if count > 1)


def _finding(
    code: KnowledgeQualityFindingCode,
    severity: _FindingSeverity,
    ranges: tuple[KnowledgeAnalysisBatchRangeStatus, ...],
    *,
    document_revision_id: str | None = None,
) -> KnowledgeQualityFinding:
    return KnowledgeQualityFinding(
        code=code,
        severity=severity,
        document_revision_id=document_revision_id,
        first_physical_page=None,
        last_physical_page=None,
        range_ids=_range_ids(ranges),
    )


def _range_ids(ranges: tuple[KnowledgeAnalysisBatchRangeStatus, ...]) -> tuple[str, ...]:
    return tuple(sorted({value.range_id for value in ranges}))[:20]


def _finding_sort_key(finding: KnowledgeQualityFinding) -> tuple[str, str, int, str]:
    return (
        finding.code.value,
        finding.document_revision_id or "",
        finding.first_physical_page or 0,
        finding.range_ids[0] if finding.range_ids else "",
    )
