"""Deterministic assessment-bundle discovery over an immutable legacy inventory."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from eom_catalog_contracts import (
    AssessmentSourceBundleProposal,
    LegacySourceInventoryEntry,
    LegacySourceInventoryV2,
)
from eom_identifiers import content_sha256

_ANSWER_TOKENS = ("정답", "해설", "답안", "answer", "solution")
_SUBJECT_TOKENS = (
    "통합과학",
    "물리학",
    "물리",
    "화학",
    "생명과학",
    "생명",
    "지구과학",
    "지구",
)
_YEAR = re.compile(r"(?<![0-9])(19[0-9]{2}|20[0-9]{2}|21[0-9]{2})(?![0-9])")


class AssessmentBundleDiscoveryError(ValueError):
    """Raised when the immutable inventory cannot be projected safely."""


def discover_assessment_source_bundle_proposals(
    inventory: LegacySourceInventoryV2,
) -> tuple[AssessmentSourceBundleProposal, ...]:
    """Group ITEM inventory entries by reviewed directory without touching source files.

    Dominant operations are one ordered pass and keyed grouping, giving O(n log n) time
    for deterministic output ordering and O(n) auxiliary pointer storage.
    """

    groups: dict[str, list[LegacySourceInventoryEntry]] = defaultdict(list)
    for entry in inventory.entries:
        if (
            entry.preliminary_class == "ORIGINAL_SOURCE_CANDIDATE"
            and entry.source_family == "ITEM"
            and entry.content_sha256 is not None
            and entry.media_type is not None
            and not entry.exclusion_reasons
        ):
            groups[str(PurePosixPath(entry.relative_path).parent)].append(entry)

    proposals: list[AssessmentSourceBundleProposal] = []
    for directory in sorted(groups, key=lambda value: (value.casefold(), value)):
        entries = tuple(
            sorted(
                groups[directory],
                key=lambda value: (value.relative_path.casefold(), value.relative_path),
            )
        )
        if not entries:
            continue
        proposals.append(_proposal(inventory, directory, entries))
    return tuple(proposals)


def _proposal(
    inventory: LegacySourceInventoryV2,
    directory: str,
    entries: tuple[LegacySourceInventoryEntry, ...],
) -> AssessmentSourceBundleProposal:
    roles = tuple((_source_role(entry), entry) for entry in entries)
    role_counts = {
        role: sum(candidate_role == role for candidate_role, _entry in roles)
        for role in {candidate_role for candidate_role, _entry in roles}
    }
    entry_keys = tuple(entry.entry_key for entry in entries)
    conflicts: list[dict[str, object]] = []
    for role, field in (
        ("PROBLEM_DOCUMENT", "members.problem_document"),
        ("ANSWER_EXPLANATION_DOCUMENT", "members.answer_explanation_document"),
    ):
        count = role_counts.get(role, 0)
        if count == 0:
            conflicts.append(
                _conflict(
                    inventory=inventory,
                    directory=directory,
                    field=field,
                    kind="MISSING_SOURCE",
                    source_entry_keys=entry_keys,
                    description=f"reviewed bundle has no {role.lower()} candidate",
                )
            )
        elif count > 1:
            conflicting_entries = tuple(
                entry.entry_key for candidate_role, entry in roles if candidate_role == role
            )
            conflicts.append(
                _conflict(
                    inventory=inventory,
                    directory=directory,
                    field=field,
                    kind="AMBIGUOUS_BUNDLE",
                    source_entry_keys=conflicting_entries,
                    description=f"reviewed bundle has multiple {role.lower()} candidates",
                )
            )

    identity_sha = content_sha256(
        {
            "schema_version": "assessment-source-bundle-proposal-identity/1.0",
            "inventory_id": inventory.inventory_id,
            "inventory_sha256": inventory.inventory_sha256,
            "directory": directory,
            "entry_keys": entry_keys,
        }
    )
    year = _observed_year(directory)
    subject = _observed_subject(directory)
    payload: dict[str, object] = {
        "schema_version": "assessment-source-bundle-proposal/1.0",
        "proposal_id": "assessbundleproposal_" + identity_sha.removeprefix("sha256:")[:32],
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "candidate_key": "assessment.bundle." + identity_sha.removeprefix("sha256:")[:32],
        "members": [
            {
                "source": {
                    "inventory_id": inventory.inventory_id,
                    "inventory_sha256": inventory.inventory_sha256,
                    "entry_key": entry.entry_key,
                    "content_sha256": entry.content_sha256,
                },
                "proposed_role": role,
                "pairing_reason_codes": ["SAME_REVIEWED_DIRECTORY"],
                "confidence_milli": 700,
            }
            for role, entry in roles
        ],
        "occurrence_observation": {
            "organization_label": None,
            "exam_family_label": PurePosixPath(directory).name or directory,
            "administration_year": year,
            "administration_date": None,
            "session_label": None,
            "subject_label": subject,
            "form_label": None,
            "source_entry_keys": list(entry_keys),
        },
        "conflicts": conflicts,
        "created_at": inventory.observed_at.isoformat().replace("+00:00", "Z"),
    }
    payload["proposal_sha256"] = content_sha256(payload)
    try:
        return AssessmentSourceBundleProposal.model_validate(payload)
    except ValueError as exc:
        raise AssessmentBundleDiscoveryError(
            "assessment bundle proposal does not satisfy its closed contract"
        ) from exc


def _source_role(entry: LegacySourceInventoryEntry) -> str:
    path = PurePosixPath(entry.relative_path)
    suffix = path.suffix.casefold()
    folded_name = path.name.casefold()
    if suffix == ".pdf":
        if any(token in folded_name for token in _ANSWER_TOKENS):
            return "ANSWER_EXPLANATION_DOCUMENT"
        return "PROBLEM_DOCUMENT"
    if suffix in {".hwp", ".hwpx"}:
        return "STRUCTURED_RECONSTRUCTION"
    if suffix == ".xlsx":
        return "ITEM_CLASSIFICATION_WORKBOOK"
    if suffix == ".csv":
        return "TYPE_CODE_REFERENCE"
    return "OTHER_REVIEWED_EVIDENCE"


def _observed_year(directory: str) -> int | None:
    matches = tuple(_YEAR.findall(directory))
    return int(matches[-1]) if matches else None


def _observed_subject(directory: str) -> str:
    folded = directory.casefold()
    for token in _SUBJECT_TOKENS:
        if token.casefold() in folded:
            return token
    return "미확정"


def _conflict(
    *,
    inventory: LegacySourceInventoryV2,
    directory: str,
    field: str,
    kind: str,
    source_entry_keys: tuple[str, ...],
    description: str,
) -> dict[str, object]:
    identity = content_sha256(
        {
            "schema_version": "assessment-bundle-conflict-identity/1.0",
            "inventory_id": inventory.inventory_id,
            "directory": directory,
            "field": field,
            "kind": kind,
            "source_entry_keys": source_entry_keys,
        }
    )
    return {
        "conflict_id": "assessmentconflict_" + identity.removeprefix("sha256:")[:32],
        "field_path": field,
        "conflict_kind": kind,
        "source_entry_keys": list(source_entry_keys),
        "description": description,
        "blocking": True,
    }
