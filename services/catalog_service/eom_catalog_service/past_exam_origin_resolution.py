"""Authoritative bulk resolution of past-exam Item placement provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from eom_catalog_contracts import ApprovedPastExamItemKnowledgeSourceV3
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRecord,
    AssessmentOccurrenceRevisionRecord,
    ItemOriginDerivationRecord,
    ItemOriginOccurrenceRecord,
    ItemOriginProfileRecord,
)
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord


class PastExamOriginStatus(StrEnum):
    """Result of validating an otherwise in-scope immutable past-exam origin."""

    ELIGIBLE = "ELIGIBLE"
    POLICY_EXCLUDED = "POLICY_EXCLUDED"


class PastExamOriginResolutionError(ValueError):
    """A stable invalid-origin error with content-free identity context."""

    code = "PAST_EXAM_ORIGIN_INVALID"

    def __init__(self, *, analysis_run_id: str, item_revision_id: str, reason: str) -> None:
        self.analysis_run_id = analysis_run_id
        self.item_revision_id = item_revision_id
        self.reason = reason
        super().__init__(
            f"{self.code}: {reason}; analysis_run_id={analysis_run_id}; "
            f"item_revision_id={item_revision_id}"
        )


@dataclass(frozen=True)
class PastExamOriginInput:
    analysis_run_id: str
    source: ApprovedPastExamItemKnowledgeSourceV3


@dataclass(frozen=True)
class PastExamOriginResolution:
    analysis_run_id: str
    item_id: str
    item_revision_id: str
    item_origin_profile_id: str
    item_origin_profile_sha256: str
    extraction_acceptance_id: str
    extraction_acceptance_sha256: str
    assessment_source_bundle_id: str
    assessment_source_bundle_revision_id: str
    assessment_source_bundle_sha256: str
    assessment_occurrence_id: str
    assessment_occurrence_revision_id: str
    assessment_occurrence_revision_sha256: str
    occurrence_display_label: str
    administration_year: int
    administration_month: int
    target_school_level: str
    target_grade: int
    subject_key: str
    item_number: int
    status: PastExamOriginStatus


def past_exam_origin_inputs(
    analyses: tuple[AcceptedAnalysisProposal, ...],
) -> tuple[PastExamOriginInput, ...]:
    """Require exact V3 visual sources without accepting the less specific V2 base type."""

    inputs: list[PastExamOriginInput] = []
    for analysis in analyses:
        source = analysis.source
        if not isinstance(source, ApprovedPastExamItemKnowledgeSourceV3):
            raise PastExamOriginResolutionError(
                analysis_run_id=analysis.analysis_run_id,
                item_revision_id=getattr(source, "item_revision_id", "unknown"),
                reason="past_exam_source_contract_invalid",
            )
        inputs.append(PastExamOriginInput(analysis_run_id=analysis.analysis_run_id, source=source))
    return tuple(inputs)


def resolve_past_exam_origins(
    session: Session,
    inputs: tuple[PastExamOriginInput, ...],
) -> tuple[PastExamOriginResolution, ...]:
    """Resolve strict new-publication origins using fixed-count indexed bulk reads.

    The one-time configured corpus is 520 Items and each Graph write is at most 16 Items.  Maps and
    sets provide O(1) identity lookup after a fixed number of set-oriented reads.  Validating all
    pending rows on each cycle is bounded at this scale and deliberately simpler than a mutable
    cache or keyset cursor, either of which could hide an invalid row behind the next write batch.
    Historical source replay has broader lifecycle rules; this resolver protects a *new* Graph
    placement and therefore retains the existing strict current/REVIEWED/APPROVED policy.
    """

    if not inputs:
        return ()

    def invalid(origin: PastExamOriginInput, reason: str) -> NoReturn:
        raise PastExamOriginResolutionError(
            analysis_run_id=origin.analysis_run_id,
            item_revision_id=origin.source.item_revision_id,
            reason=reason,
        )

    analysis_ids = tuple(origin.analysis_run_id for origin in inputs)
    revision_ids = tuple(origin.source.item_revision_id for origin in inputs)
    if len(analysis_ids) != len(set(analysis_ids)):
        invalid(inputs[0], "duplicate_analysis_run")
    if len(revision_ids) != len(set(revision_ids)):
        invalid(inputs[0], "duplicate_item_revision")

    profiles_by_revision: dict[str, list[ItemOriginProfileRecord]] = {}
    for profile in session.scalars(
        select(ItemOriginProfileRecord).where(
            ItemOriginProfileRecord.item_revision_id.in_(revision_ids)
        )
    ):
        profiles_by_revision.setdefault(profile.item_revision_id, []).append(profile)
    profile_ids = tuple(
        sorted(
            {
                profile.item_origin_profile_id
                for profiles in profiles_by_revision.values()
                for profile in profiles
            }
        )
    )

    occurrences_by_profile: dict[str, list[ItemOriginOccurrenceRecord]] = {}
    derivations_by_profile: dict[str, list[ItemOriginDerivationRecord]] = {}
    if profile_ids:
        for occurrence_link in session.scalars(
            select(ItemOriginOccurrenceRecord).where(
                ItemOriginOccurrenceRecord.item_origin_profile_id.in_(profile_ids)
            )
        ):
            occurrences_by_profile.setdefault(occurrence_link.item_origin_profile_id, []).append(
                occurrence_link
            )
        for derivation in session.scalars(
            select(ItemOriginDerivationRecord).where(
                ItemOriginDerivationRecord.item_origin_profile_id.in_(profile_ids),
                ItemOriginDerivationRecord.source_kind == "ASSESSMENT_SOURCE_BUNDLE_REVISION",
            )
        ):
            derivations_by_profile.setdefault(derivation.item_origin_profile_id, []).append(
                derivation
            )

    occurrence_revision_ids = tuple(
        sorted(
            {
                link.assessment_occurrence_revision_id
                for links in occurrences_by_profile.values()
                for link in links
            }
        )
    )
    occurrences = (
        {
            row.assessment_occurrence_revision_id: row
            for row in session.scalars(
                select(AssessmentOccurrenceRevisionRecord).where(
                    AssessmentOccurrenceRevisionRecord.assessment_occurrence_revision_id.in_(
                        occurrence_revision_ids
                    )
                )
            )
        }
        if occurrence_revision_ids
        else {}
    )
    occurrence_ids = tuple(
        sorted(
            {
                link.assessment_occurrence_id
                for links in occurrences_by_profile.values()
                for link in links
            }
        )
    )
    occurrence_logicals = (
        {
            row.assessment_occurrence_id: row
            for row in session.scalars(
                select(AssessmentOccurrenceRecord).where(
                    AssessmentOccurrenceRecord.assessment_occurrence_id.in_(occurrence_ids)
                )
            )
        }
        if occurrence_ids
        else {}
    )

    bundle_revision_ids = tuple(
        sorted(
            {origin.source.bundle.assessment_source_bundle_revision_id for origin in inputs}
            | {
                derivation.revision_id
                for derivations in derivations_by_profile.values()
                for derivation in derivations
            }
        )
    )
    bundles = {
        row.assessment_source_bundle_revision_id: row
        for row in session.scalars(
            select(AssessmentSourceBundleRevisionRecord).where(
                AssessmentSourceBundleRevisionRecord.assessment_source_bundle_revision_id.in_(
                    bundle_revision_ids
                )
            )
        )
    }

    acceptance_ids = tuple(sorted({origin.source.extraction_acceptance_id for origin in inputs}))
    acceptances = {
        row.acceptance_id: row
        for row in session.scalars(
            select(LegacyItemExtractionAcceptanceRecord).where(
                LegacyItemExtractionAcceptanceRecord.acceptance_id.in_(acceptance_ids)
            )
        )
    }
    decisions_by_acceptance: dict[str, list[LegacyItemExtractionDecisionRecord]] = {}
    for decision in session.scalars(
        select(LegacyItemExtractionDecisionRecord).where(
            LegacyItemExtractionDecisionRecord.acceptance_id.in_(acceptance_ids)
        )
    ):
        decisions_by_acceptance.setdefault(decision.acceptance_id, []).append(decision)
    revisions = {
        row.item_revision_id: row
        for row in session.scalars(
            select(ItemRevisionRecord).where(ItemRevisionRecord.item_revision_id.in_(revision_ids))
        )
    }
    item_ids = tuple(sorted({origin.source.item_id for origin in inputs}))
    items = {
        row.item_id: row
        for row in session.scalars(select(ItemRecord).where(ItemRecord.item_id.in_(item_ids)))
    }

    resolutions: list[PastExamOriginResolution] = []
    for origin in inputs:
        source = origin.source
        profiles = profiles_by_revision.get(source.item_revision_id, [])
        if len(profiles) != 1:
            invalid(origin, "origin_profile_cardinality")
        profile = profiles[0]
        occurrence_links = occurrences_by_profile.get(profile.item_origin_profile_id, [])
        if len(occurrence_links) != 1:
            invalid(origin, "origin_occurrence_cardinality")
        derivations = derivations_by_profile.get(profile.item_origin_profile_id, [])
        if len(derivations) != 1:
            invalid(origin, "origin_derivation_cardinality")
        matching_decisions = tuple(
            decision
            for decision in decisions_by_acceptance.get(source.extraction_acceptance_id, [])
            if decision.item_proposal_id == source.item_proposal_id
        )
        if len(matching_decisions) != 1:
            invalid(origin, "extraction_decision_cardinality")

        occurrence_link = occurrence_links[0]
        derivation = derivations[0]
        decision = matching_decisions[0]
        occurrence = occurrences.get(occurrence_link.assessment_occurrence_revision_id)
        logical = occurrence_logicals.get(occurrence_link.assessment_occurrence_id)
        bundle = bundles.get(derivation.revision_id)
        acceptance = acceptances.get(source.extraction_acceptance_id)
        revision = revisions.get(source.item_revision_id)
        item = items.get(source.item_id)
        if occurrence is None:
            invalid(origin, "occurrence_revision_missing")
        if logical is None:
            invalid(origin, "occurrence_logical_missing")
        if bundle is None:
            invalid(origin, "bundle_revision_missing")
        if acceptance is None:
            invalid(origin, "extraction_acceptance_missing")
        if revision is None or item is None:
            invalid(origin, "item_revision_missing")

        if (
            revision.item_id != source.item_id
            or revision.revision_state != "APPROVED"
            or revision.registration_key
            != (
                f"legacy-item-promotion:{source.extraction_acceptance_id}:{source.item_proposal_id}"
            )
            or item.lifecycle_state != "ACTIVE"
            or item.current_revision_id != source.item_revision_id
            or profile.item_id != source.item_id
            or profile.item_revision_id != source.item_revision_id
            or profile.item_manifest_sha256 != revision.manifest_sha256
            or profile.source_domain != "EXTERNAL_INSTITUTION"
        ):
            invalid(origin, "item_revision_or_profile_invalid")
        if (
            occurrence_link.assessment_occurrence_id != occurrence.assessment_occurrence_id
            or occurrence_link.assessment_occurrence_revision_id
            != occurrence.assessment_occurrence_revision_id
            or occurrence_link.occurrence_revision_sha256 != occurrence.revision_sha256
            or occurrence.schema_version != "assessment-occurrence-revision/2.0"
            or occurrence.revision_state != "REVIEWED"
            or occurrence.administration_month is None
            or occurrence.target_school_level is None
            or occurrence.target_grade is None
        ):
            invalid(origin, "occurrence_revision_invalid")
        if (
            logical.assessment_occurrence_id != occurrence.assessment_occurrence_id
            or logical.lifecycle_state != "ACTIVE"
            or logical.current_revision_id != occurrence.assessment_occurrence_revision_id
        ):
            invalid(origin, "occurrence_logical_invalid")
        if (
            derivation.source_kind != "ASSESSMENT_SOURCE_BUNDLE_REVISION"
            or derivation.relation != "DIGITIZED_FROM"
            or derivation.logical_id != source.bundle.assessment_source_bundle_id
            or derivation.revision_id != source.bundle.assessment_source_bundle_revision_id
            or derivation.manifest_sha256 != source.bundle.bundle_manifest_sha256
            or bundle.assessment_source_bundle_id != source.bundle.assessment_source_bundle_id
            or bundle.assessment_source_bundle_revision_id
            != source.bundle.assessment_source_bundle_revision_id
            or bundle.bundle_manifest_sha256 != source.bundle.bundle_manifest_sha256
            or bundle.state != "REVIEWED"
            or bundle.assessment_occurrence_id != occurrence.assessment_occurrence_id
            or bundle.assessment_occurrence_revision_id
            != occurrence.assessment_occurrence_revision_id
            or bundle.occurrence_revision_sha256 != occurrence.revision_sha256
        ):
            invalid(origin, "bundle_derivation_invalid")
        if (
            profile.rights_policy_id != bundle.rights_policy_id
            or profile.rights_policy_revision_id != bundle.rights_policy_revision_id
            or profile.rights_policy_sha256 != bundle.rights_policy_sha256
            or occurrence.rights_policy_id != bundle.rights_policy_id
            or occurrence.rights_policy_revision_id != bundle.rights_policy_revision_id
            or occurrence.rights_policy_sha256 != bundle.rights_policy_sha256
        ):
            invalid(origin, "rights_policy_invalid")

        acceptance_artifact = source.extraction_acceptance_artifact
        result_artifact = source.extraction_result_artifact
        if (
            acceptance.acceptance_sha256 != source.extraction_acceptance_sha256
            or acceptance.state != "ACCEPTED"
            or acceptance.coverage_state != "COMPLETE"
            or acceptance.extraction_result_id != source.extraction_result_id
            or acceptance.result_sha256 != source.extraction_result_sha256
            or acceptance.acceptance_artifact_id != acceptance_artifact.artifact_id
            or acceptance.acceptance_artifact_revision_id
            != acceptance_artifact.artifact_revision_id
            or acceptance.acceptance_artifact_member_path != acceptance_artifact.member_path
            or acceptance.acceptance_artifact_schema_ref != acceptance_artifact.schema_ref
            or acceptance.acceptance_artifact_media_type != acceptance_artifact.media_type
            or acceptance.acceptance_artifact_sha256 != acceptance_artifact.sha256
            or acceptance.result_artifact_id != result_artifact.artifact_id
            or acceptance.result_artifact_revision_id != result_artifact.artifact_revision_id
            or acceptance.result_artifact_member_path != result_artifact.member_path
            or acceptance.result_artifact_schema_ref != result_artifact.schema_ref
            or acceptance.result_artifact_media_type != result_artifact.media_type
            or acceptance.result_artifact_sha256 != result_artifact.sha256
        ):
            invalid(origin, "extraction_acceptance_invalid")
        if (
            decision.acceptance_id != source.extraction_acceptance_id
            or decision.item_proposal_id != source.item_proposal_id
            or decision.item_number != source.item_number
            or decision.decision not in {"ACCEPT", "CORRECT_AND_ACCEPT"}
        ):
            invalid(origin, "extraction_decision_invalid")

        administration_month = occurrence.administration_month
        target_school_level = occurrence.target_school_level
        target_grade = occurrence.target_grade
        if administration_month is None or target_school_level is None or target_grade is None:
            invalid(origin, "occurrence_audience_invalid")
        status = (
            PastExamOriginStatus.POLICY_EXCLUDED
            if (
                target_school_level == "HIGH_SCHOOL"
                and target_grade == 1
                and administration_month == 3
            )
            else PastExamOriginStatus.ELIGIBLE
        )
        resolutions.append(
            PastExamOriginResolution(
                analysis_run_id=origin.analysis_run_id,
                item_id=source.item_id,
                item_revision_id=source.item_revision_id,
                item_origin_profile_id=profile.item_origin_profile_id,
                item_origin_profile_sha256=profile.profile_sha256,
                extraction_acceptance_id=acceptance.acceptance_id,
                extraction_acceptance_sha256=acceptance.acceptance_sha256,
                assessment_source_bundle_id=bundle.assessment_source_bundle_id,
                assessment_source_bundle_revision_id=bundle.assessment_source_bundle_revision_id,
                assessment_source_bundle_sha256=bundle.bundle_manifest_sha256,
                assessment_occurrence_id=occurrence.assessment_occurrence_id,
                assessment_occurrence_revision_id=occurrence.assessment_occurrence_revision_id,
                assessment_occurrence_revision_sha256=occurrence.revision_sha256,
                occurrence_display_label=occurrence.display_label,
                administration_year=occurrence.administration_year,
                administration_month=administration_month,
                target_school_level=target_school_level,
                target_grade=target_grade,
                subject_key=occurrence.subject_key,
                item_number=decision.item_number,
                status=status,
            )
        )
    return tuple(resolutions)
