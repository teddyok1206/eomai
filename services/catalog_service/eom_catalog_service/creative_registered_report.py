"""Read registered creative solution notes without inventing an accepted V10 report."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.creative_source_lineage import (
    CREATIVE_SOURCE_LINEAGE_SCHEMA_REF,
    CreativeSourceLineage,
)
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_learning_proposal import (
    ResolvedCreativeLearningProposal,
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.creative_source_draft_materialization import (
    creative_source_draft_warning_codes,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord


class CreativeRegisteredReportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RegisteredCreativeReport:
    lineage: CreativeSourceLineage
    proposal: ResolvedCreativeLearningProposal

    def context_text(self, *, maximum_chars: int = 24000) -> str:
        """Expose all recorded conflicts with the independent answer, not just a final answer."""
        result = self.proposal.role.output.learning_result
        proposal = result.proposal
        if proposal is None:
            raise CreativeRegisteredReportError("CREATIVE_REPORT_CONTENT_MISSING")
        if isinstance(result, ExternalItemLearningResultV2):
            report = result.solution_report
            draft = result.proposal
            assert draft is not None
            editorial_ids_v2 = set(report.editorial_region_ids)
            text_v2 = canonical_json_bytes(
                {
                    "report_kind": "CREATIVE_SOURCE_SOLUTION_AND_WARNINGS_V2",
                    "approval_meaning": (
                        "원문 수록 승인입니다. 정답·풀이의 과학적 정확성 보장이 아닙니다."
                    ),
                    "independent_proposal_is_not_editorial_answer": True,
                    "source_answer_mode": self.lineage.source_answer_mode,
                    "source_score_state": draft.content.score.state,
                    "source_solution": draft.content.solution.model_dump(mode="json"),
                    "editorial_observations": [
                        {"region_id": region.region_id, "text": region.observed_text}
                        for region in result.regions
                        if region.region_id in editorial_ids_v2
                    ],
                    "independent_answer_state": report.answer_state,
                    "independent_proposal_answer": report.answer_labels or report.accepted_answers,
                    "independent_proposal_explanation": report.explanation,
                    "solution_steps": [
                        step.model_dump(mode="json") for step in report.solution_steps
                    ],
                    "answer_cross_check": report.answer_cross_check,
                    "warning_codes": self.lineage.warning_codes,
                    "issues": [issue.model_dump(mode="json") for issue in result.conflicts],
                    "original_proposal_status": result.status,
                }
            ).decode()
            if len(text_v2) > maximum_chars:
                raise CreativeRegisteredReportError("CREATIVE_REPORT_CONTEXT_TOO_LARGE")
            return text_v2
        # Narrow the historical family independently of the separate V2 report.
        proposal = result.proposal
        assert proposal is not None
        mappings = {entry.content_path: entry.region_ids for entry in proposal.content_region_map}
        editorial_ids = set(mappings.get("solution.correct_choice_ids", ())) | set(
            mappings.get("solution.explanation", ())
        )
        text = canonical_json_bytes(
            {
                "report_kind": "CREATIVE_SOURCE_SOLUTION_AND_WARNINGS_V1",
                "approval_meaning": (
                    "원문 수록 승인입니다. 정답·풀이의 과학적 정확성 보장이 아닙니다."
                ),
                "independent_proposal_is_not_editorial_answer": True,
                "source_answer_mode": self.lineage.source_answer_mode,
                "editorial_observations": [
                    {"region_id": region.region_id, "text": region.observed_text}
                    for region in result.regions
                    if region.region_id in editorial_ids and region.role == "EDITORIAL_SOLUTION"
                ],
                "independent_proposal_answer": proposal.content.solution.correct_choice_ids,
                "independent_proposal_explanation": proposal.content.solution.explanation,
                "solution_steps": [
                    step.model_dump(mode="json") for step in proposal.solution_steps
                ],
                "answer_cross_check": proposal.answer_cross_check,
                "warning_codes": self.lineage.warning_codes,
                "issues": [issue.model_dump(mode="json") for issue in result.conflicts],
                "original_proposal_status": result.status,
            }
        ).decode()
        if len(text) > maximum_chars:
            # The complete immutable role result remains stored. Never silently
            # truncate the very contradiction a future solver needs to see.
            raise CreativeRegisteredReportError("CREATIVE_REPORT_CONTEXT_TOO_LARGE")
        return text


def load_registered_creative_report(
    session: Session,
    artifacts: CatalogArtifactService,
    revision: ItemRevisionRecord,
) -> RegisteredCreativeReport:
    """Caller authorizes Item access; the report is bound to that exact revision.

    This read does not borrow the creator's browser session or require that their
    account stay active forever. Processing claims separately reauthorize the
    current task owner and source before any new mutation or worker execution.
    """
    components = tuple(
        session.scalars(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == revision.item_revision_id
            )
        )
    )
    content, lineage_component, report = creative_report_components(revision, components)
    payload = artifacts.read_member(
        artifact_id=lineage_component.artifact_id,
        revision_id=lineage_component.artifact_revision_id,
        member_path="lineage.json",
        sha256=lineage_component.sha256,
        schema_ref=CREATIVE_SOURCE_LINEAGE_SCHEMA_REF,
        media_type="application/json",
        max_bytes=64 * 1024,
    )
    lineage = CreativeSourceLineage.model_validate_json(payload)
    validate_creative_report_lineage(revision, content, report, lineage)
    resolved = resolve_completed_creative_learning_proposal(session, artifacts, lineage.selection)
    return validate_registered_creative_report(lineage, resolved)


def creative_report_components(
    revision: ItemRevisionRecord, components: tuple[ItemComponentRecord, ...]
) -> tuple[ItemComponentRecord, ItemComponentRecord, ItemComponentRecord]:
    """One exact component rule for single reads and bounded batch capture."""
    keyed = {(entry.component_type, entry.ordinal): entry for entry in components}
    content = keyed.get(("ITEM_CONTENT", 0))
    lineage_component = keyed.get(("SOURCE_REFERENCE", 0))
    report = keyed.get(("REVIEW_REPORT", 0))
    if (
        revision.metadata_json.get("source_kind") != "CREATIVE"
        or len(keyed) != len(components)
        or content is None
        or lineage_component is None
        or report is None
        or lineage_component.schema_ref != CREATIVE_SOURCE_LINEAGE_SCHEMA_REF
        or lineage_component.logical_name != "lineage.json"
        or lineage_component.media_type != "application/json"
        or report.logical_name != "result.json"
        or report.media_type != "application/json"
    ):
        raise CreativeRegisteredReportError("CREATIVE_REPORT_COMPONENT_INVALID")
    return content, lineage_component, report


def validate_creative_report_lineage(
    revision: ItemRevisionRecord,
    content: ItemComponentRecord,
    report: ItemComponentRecord,
    lineage: CreativeSourceLineage,
) -> None:
    """Pure closure check, never permission to resolve any Artifact."""
    metadata = revision.metadata_json
    pointer = ArtifactMemberPointer(
        artifact_id=report.artifact_id,
        artifact_revision_id=report.artifact_revision_id,
        member_path="result.json",
        schema_ref=report.schema_ref,
        media_type="application/json",
        sha256=report.sha256,
    )
    if (
        metadata.get("lineage_sha256") != lineage.lineage_sha256
        or metadata.get("source_id") != lineage.source_id
        or metadata.get("source_revision_id") != lineage.source_revision_id
        or metadata.get("external_number") != lineage.external_number
        or lineage.selection.workflow_id != revision.workflow_id
        or lineage.selection.step_run_id != revision.source_workflow_step_run_id
        or lineage.registered_content_sha256 != content.sha256
        or lineage.role_result != pointer
    ):
        raise CreativeRegisteredReportError("CREATIVE_REPORT_LINEAGE_MISMATCH")


def validate_registered_creative_report(
    lineage: CreativeSourceLineage, resolved: ResolvedCreativeLearningProposal
) -> RegisteredCreativeReport:
    """Shared original source/solution checks after actual completed-job resolution."""
    result, source = resolved.role.output.learning_result, resolved.work.source
    if (
        resolved.pointer != lineage.role_result
        or result.result_id != lineage.result_id
        or result.result_sha256 != lineage.result_sha256
        or result.proposal is None
        or content_sha256(result.proposal.content.model_dump(mode="json"))
        != lineage.proposed_content_sha256
        or source.source_id != lineage.source_id
        or source.source_revision_id != lineage.source_revision_id
        or source.import_id != lineage.import_id
        or source.external_number != lineage.external_number
        or source.origin_kind != lineage.origin_kind
        or source.input_sha256 != lineage.source_input_sha256
        or source.observation_sha256 != lineage.observation_sha256
        or resolved.operator_id != lineage.requested_by_operator_id
        or not {issue.conflict_code for issue in result.conflicts}.issubset(lineage.warning_codes)
    ):
        raise CreativeRegisteredReportError("CREATIVE_REPORT_SOURCE_MISMATCH")
    if isinstance(result, ExternalItemLearningResultV2):
        assert result.proposal is not None
        draft = result.proposal.content
        expected_mode = (
            "EDITORIAL_SOURCE"
            if draft.solution_origin == "EDITORIAL_SOURCE"
            else "MODEL_PROPOSAL_UNVERIFIED"
        )
        if (
            not set(creative_source_draft_warning_codes(draft)).issubset(lineage.warning_codes)
            or lineage.source_answer_mode != expected_mode
        ):
            raise CreativeRegisteredReportError("CREATIVE_REPORT_SOURCE_MISMATCH")
    return RegisteredCreativeReport(lineage, resolved)
