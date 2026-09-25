"""Deterministic metadata resolution for immutable science-assessment acquisitions."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import cast

from eom_catalog_contracts import (
    ScienceAssessmentAcquisitionSuccess,
    ScienceAssessmentMetadataResolution,
    ScienceAssessmentMetadataResolutionPolicy,
    ScienceAssessmentMetadataResolutionSummary,
    ScienceAssessmentResolvedDocumentMetadata,
    ScienceAssessmentWebAcquisition,
    validate_science_metadata_resolution_against_acquisition,
)
from eom_catalog_contracts.science_assessment_corpus import (
    GradeResolutionRule,
    IssuerResolutionRule,
    IssuerType,
    SessionResolutionRule,
    SubjectFamily,
    SubjectResolutionRule,
    YearResolutionRule,
)
from eom_identifiers import content_sha256

SUBJECT_RULES: tuple[SubjectResolutionRule, ...] = (
    "MULTI_SUBJECT_LIST",
    "EXPLICIT_INTEGRATED_SCIENCE",
    "EXPLICIT_SINGLE_SUBJECT",
    "GENERIC_SCIENCE_INQUIRY",
    "ACQUISITION_FALLBACK",
)
ISSUER_RULES: tuple[IssuerResolutionRule, ...] = (
    "EXPLICIT_KICE",
    "EXPLICIT_EDUCATION_AUTHORITY",
    "ACQUISITION_FALLBACK",
)
YEAR_RULES: tuple[YearResolutionRule, ...] = (
    "EXPLICIT_ADMINISTRATION_YEAR",
    "EXPLICIT_CALENDAR_YEAR",
    "EXPLICIT_ACADEMIC_YEAR",
    "ACQUISITION_FALLBACK",
)
GRADE_RULES: tuple[GradeResolutionRule, ...] = (
    "KICE_FIXED_GRADE_3",
    "EXPLICIT_GRADE",
    "ACQUISITION_FALLBACK",
)
SESSION_RULES: tuple[SessionResolutionRule, ...] = (
    "EXPLICIT_KICE_CSAT",
    "EXPLICIT_MONTH",
    "ACQUISITION_FALLBACK",
)

_LEVEL = r"(?P<level>[12]|\u2160|\u2161|I{1,2})?"
_SUBJECT_PATTERNS: tuple[tuple[SubjectFamily, re.Pattern[str]], ...] = (
    ("INTEGRATED_SCIENCE", re.compile(r"통합\s*과학", re.IGNORECASE)),
    (
        "LIFE_SCIENCE",
        re.compile(rf"(?P<base>생명\s*과학|생물)\s*{_LEVEL}", re.IGNORECASE),
    ),
    (
        "EARTH_SCIENCE",
        re.compile(rf"(?P<base>지구\s*과학)\s*{_LEVEL}", re.IGNORECASE),
    ),
    (
        "EARTH_SCIENCE",
        re.compile(r"(?P<base>지구\s*과)\s*(?P<level>[12])\s*학", re.IGNORECASE),
    ),
    (
        "CHEMISTRY",
        re.compile(rf"(?P<base>화학)\s*{_LEVEL}", re.IGNORECASE),
    ),
    (
        "PHYSICS",
        re.compile(rf"(?P<base>물리(?:학)?)\s*{_LEVEL}", re.IGNORECASE),
    ),
)


class ScienceAssessmentMetadataResolutionError(RuntimeError):
    """Stable, content-free resolution failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Evidence:
    rank: int
    value: Hashable
    rule: str


def science_assessment_metadata_resolution_policy() -> ScienceAssessmentMetadataResolutionPolicy:
    value: dict[str, object] = {
        "schema_version": "science-assessment-metadata-resolution-policy/1.0",
        "policy_id": "sciencecorpuspolicy_" + "0" * 32,
        "algorithm": "EOM_SCIENCE_METADATA_RESOLVER_2026_09_25_A",
        "subject_rules": list(SUBJECT_RULES),
        "issuer_rules": list(ISSUER_RULES),
        "year_rules": list(YEAR_RULES),
        "grade_rules": list(GRADE_RULES),
        "session_rules": list(SESSION_RULES),
        "policy_sha256": "sha256:" + "0" * 64,
    }
    identity = content_sha256(
        {key: item for key, item in value.items() if key not in {"policy_id", "policy_sha256"}}
    )
    value["policy_id"] = "sciencecorpuspolicy_" + identity.removeprefix("sha256:")[:32]
    value["policy_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "policy_sha256"}
    )
    return ScienceAssessmentMetadataResolutionPolicy.model_validate(value)


def resolve_science_assessment_metadata(
    acquisition: ScienceAssessmentWebAcquisition,
) -> ScienceAssessmentMetadataResolution:
    """Resolve every unique PDF in O(observations) time and fail on equal-rank disagreement."""

    grouped: dict[str, list[ScienceAssessmentAcquisitionSuccess]] = {}
    for observation in acquisition.successful_observations:
        grouped.setdefault(observation.sha256, []).append(observation)

    documents: list[ScienceAssessmentResolvedDocumentMetadata] = []
    for content_hash, observations in sorted(grouped.items()):
        first = observations[0]
        byte_identities = {(value.bytes, value.page_count) for value in observations}
        if len(byte_identities) != 1:
            raise ScienceAssessmentMetadataResolutionError(
                "SCIENCE_CORPUS_CONTENT_METADATA_CONFLICT"
            )
        subject_value, subject_rule = _select(observations, _subject_evidence)
        subject = cast(tuple[SubjectFamily, str], subject_value)
        issuer_value, issuer_rule = _select(observations, _issuer_evidence)
        issuer = cast(IssuerType, issuer_value)
        year, year_rule = _select(
            observations,
            partial(_year_evidence, issuer=issuer),
        )
        grade, grade_rule = _select(
            observations,
            partial(_grade_evidence, issuer=issuer),
        )
        session, session_rule = _select(
            observations,
            partial(_session_evidence, issuer=issuer),
        )
        year = cast(int, year)
        grade = cast(int, grade)
        session = cast(str, session)
        subject_family, subject_label = subject
        resolved_identity = (subject_family, issuer, year, grade, session)
        raw_identities = {
            (
                value.subject_family,
                value.issuer_type,
                value.administration_year,
                value.grade,
                value.session_label,
            )
            for value in observations
        }
        changed = any(
            (
                value.subject_family,
                value.subject_label,
                value.issuer_type,
                value.administration_year,
                value.grade,
                value.session_label,
            )
            != (subject_family, subject_label, issuer, year, grade, session)
            for value in observations
        )
        documents.append(
            ScienceAssessmentResolvedDocumentMetadata(
                sha256=content_hash,
                bytes=first.bytes,
                page_count=first.page_count,
                original_filename=min(value.original_filename for value in observations),
                subject_family=subject_family,
                subject_label=subject_label,
                subject_rule=cast(SubjectResolutionRule, subject_rule),
                issuer_type=issuer,
                issuer_rule=cast(IssuerResolutionRule, issuer_rule),
                administration_year=year,
                year_rule=cast(YearResolutionRule, year_rule),
                grade=grade,
                grade_rule=cast(GradeResolutionRule, grade_rule),
                session_label=session,
                session_rule=cast(SessionResolutionRule, session_rule),
                observation_count=len(observations),
                had_metadata_conflict=len(raw_identities) > 1,
                metadata_changed=changed or resolved_identity not in raw_identities,
            )
        )

    policy = science_assessment_metadata_resolution_policy()
    summary = ScienceAssessmentMetadataResolutionSummary(
        unique_document_count=len(documents),
        successful_observation_count=sum(value.observation_count for value in documents),
        conflicting_document_count=sum(value.had_metadata_conflict for value in documents),
        normalized_document_count=sum(value.metadata_changed for value in documents),
    )
    value: dict[str, object] = {
        "schema_version": "science-assessment-metadata-resolution/1.0",
        "plan_id": acquisition.plan_id,
        "plan_sha256": acquisition.plan_sha256,
        "acquisition_sha256": acquisition.acquisition_sha256,
        "policy": policy.model_dump(mode="json"),
        "documents": [item.model_dump(mode="json") for item in documents],
        "summary": summary.model_dump(mode="json"),
        "resolution_sha256": "sha256:" + "0" * 64,
    }
    value["resolution_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "resolution_sha256"}
    )
    resolution = ScienceAssessmentMetadataResolution.model_validate(value)
    validate_science_metadata_resolution_against_acquisition(resolution, acquisition)
    return resolution


def _select(
    observations: Sequence[ScienceAssessmentAcquisitionSuccess],
    evidence: Callable[[ScienceAssessmentAcquisitionSuccess], _Evidence],
) -> tuple[Hashable, str]:
    candidates = tuple(evidence(value) for value in observations)
    rank = max(value.rank for value in candidates)
    winners = {(value.value, value.rule) for value in candidates if value.rank == rank}
    if len(winners) != 1:
        raise ScienceAssessmentMetadataResolutionError(
            "SCIENCE_CORPUS_METADATA_RESOLUTION_AMBIGUOUS"
        )
    return next(iter(winners))


def _source_text(value: ScienceAssessmentAcquisitionSuccess) -> str:
    return unicodedata.normalize("NFC", f"{value.link_text} {value.download_url}")


def _subject_evidence(value: ScienceAssessmentAcquisitionSuccess) -> _Evidence:
    text = _source_text(value)
    matches: dict[SubjectFamily, set[str]] = {}
    for family, pattern in _SUBJECT_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            matches.setdefault(family, set()).add(_subject_label(family, match))
    if len(matches) >= 2:
        return _Evidence(500, ("GENERAL_SCIENCE", "과학탐구"), "MULTI_SUBJECT_LIST")
    if len(matches) == 1:
        family = next(iter(matches))
        labels = matches[family]
        if len(labels) != 1:
            raise ScienceAssessmentMetadataResolutionError(
                "SCIENCE_CORPUS_METADATA_RESOLUTION_AMBIGUOUS"
            )
        rule = (
            "EXPLICIT_INTEGRATED_SCIENCE"
            if family == "INTEGRATED_SCIENCE"
            else "EXPLICIT_SINGLE_SUBJECT"
        )
        return _Evidence(
            475 if family == "INTEGRATED_SCIENCE" else 450, (family, next(iter(labels))), rule
        )
    if re.search(r"과학\s*탐구|과탐", text):
        return _Evidence(300, ("GENERAL_SCIENCE", "과학탐구"), "GENERIC_SCIENCE_INQUIRY")
    return _Evidence(
        100,
        (value.subject_family, value.subject_label),
        "ACQUISITION_FALLBACK",
    )


def _subject_label(family: SubjectFamily, match: re.Match[str]) -> str:
    if family == "INTEGRATED_SCIENCE":
        return "통합과학"
    level = match.groupdict().get("level") or ""
    level = {"\u2160": "1", "I": "1", "\u2161": "2", "II": "2"}.get(level.upper(), level)
    if family == "PHYSICS":
        base = "물리학"
    elif family == "CHEMISTRY":
        base = "화학"
    elif family == "LIFE_SCIENCE":
        # Historical "생물" aliases and current "생명과학" labels describe the same
        # subject family in this corpus.  Normalizing the display label prevents an
        # exact-byte duplicate from depending on which public alias was discovered first.
        base = "생명과학"
    else:
        base = "지구과학"
    return base + level


def _issuer_evidence(value: ScienceAssessmentAcquisitionSuccess) -> _Evidence:
    text = _source_text(value)
    kice = bool(re.search(r"평가원|모의평가|수능", text))
    authority = bool(re.search(r"학력평가|교육청", text))
    if kice and authority:
        raise ScienceAssessmentMetadataResolutionError(
            "SCIENCE_CORPUS_METADATA_RESOLUTION_AMBIGUOUS"
        )
    if kice:
        return _Evidence(500, "KICE", "EXPLICIT_KICE")
    if authority:
        return _Evidence(500, "EDUCATION_AUTHORITY", "EXPLICIT_EDUCATION_AUTHORITY")
    return _Evidence(
        100,
        value.issuer_type,
        "ACQUISITION_FALLBACK",
    )


def _year_evidence(
    value: ScienceAssessmentAcquisitionSuccess,
    *,
    issuer: IssuerType,
) -> _Evidence:
    text = _source_text(value)
    explicit = re.search(r"((?:19|20)\d{2})\s*년[^\n]{0,40}?시행", text)
    if explicit is not None:
        return _Evidence(500, int(explicit.group(1)), "EXPLICIT_ADMINISTRATION_YEAR")
    calendar = re.search(r"((?:19|20)\d{2})\s*년\s*(?:[0-9]{1,2}\s*월|수능)", text)
    if calendar is not None:
        return _Evidence(450, int(calendar.group(1)), "EXPLICIT_CALENDAR_YEAR")
    academic = re.search(r"((?:19|20)\d{2})\s*학년도", text)
    if academic is not None:
        value_year = int(academic.group(1)) - (1 if issuer == "KICE" else 0)
        return _Evidence(400, value_year, "EXPLICIT_ACADEMIC_YEAR")
    return _Evidence(
        100,
        value.administration_year,
        "ACQUISITION_FALLBACK",
    )


def _grade_evidence(
    value: ScienceAssessmentAcquisitionSuccess,
    *,
    issuer: IssuerType,
) -> _Evidence:
    if issuer == "KICE":
        return _Evidence(500, 3, "KICE_FIXED_GRADE_3")
    grade = re.search(r"(?:고등학교\s*|고\s*)([123])(?:\s*학년)?", _source_text(value))
    if grade is not None:
        return _Evidence(450, int(grade.group(1)), "EXPLICIT_GRADE")
    return _Evidence(100, value.grade, "ACQUISITION_FALLBACK")


def _session_evidence(
    value: ScienceAssessmentAcquisitionSuccess,
    *,
    issuer: IssuerType,
) -> _Evidence:
    text = _source_text(value)
    if issuer == "KICE" and "수능" in text and "모의평가" not in text:
        return _Evidence(600, "대학수학능력시험", "EXPLICIT_KICE_CSAT")
    month = re.search(r"(?<!\d)(1[0-2]|[1-9])\s*월", text)
    if month is not None:
        kind = "모의평가" if issuer == "KICE" else "학력평가"
        return _Evidence(500, f"{int(month.group(1))}월 {kind}", "EXPLICIT_MONTH")
    return _Evidence(
        100,
        value.session_label,
        "ACQUISITION_FALLBACK",
    )
