"""Resolve ranked immutable Item pointers through one existing Graph projection."""

from collections.abc import Callable

from eom_api_contracts.item_bank import ProductionItemCandidateViewContract
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from pydantic import TypeAdapter

from eom_api.errors import ApiError


def _matches_canonical_component(
    candidate: ProductionItemCandidateViewContract, source: PopulationSource
) -> bool:
    component, member = candidate.content_component, source.artifact_member
    return component is not None and (
        component.artifact_id,
        component.artifact_revision_id,
        component.sha256,
        component.schema_ref,
        component.media_type,
        component.logical_name,
    ) == (
        member.artifact_id,
        member.artifact_revision_id,
        member.sha256,
        member.schema_ref,
        member.media_type,
        # The worker's logical_name is a staging alias, not the canonical member.
        member.member_path,
    )


def read_selected_item_candidates(
    selections: tuple[PopulationSource, ...],
    read_candidates: Callable[
        [tuple[PopulationSource, ...]], tuple[ProductionItemCandidateViewContract, ...]
    ],
) -> tuple[ProductionItemCandidateViewContract, ...]:
    """One batch read, O(n) matching, original rank order; no latest Item fallback.

    The existing Graph projection owns eligibility/lifecycle. Its caller owns
    request authorization; this boundary only translates exact result pointers.
    """
    pins: tuple[PopulationSource, ...] = TypeAdapter(tuple[PopulationSource, ...]).validate_python(
        selections
    )
    if not 1 <= len(pins) <= 64 or len({pin.item_revision_id for pin in pins}) != len(pins):
        raise ValueError("selected Item revisions must be bounded and unique")
    values = read_candidates(pins)
    by_revision = {row.item_revision_id: row for row in values}
    if (
        len(by_revision) != len(values)
        or set(by_revision) != {pin.item_revision_id for pin in pins}
        or any(
            by_revision[pin.item_revision_id].item_id != pin.item_id
            or by_revision[pin.item_revision_id].source_class != pin.source_class
            or not _matches_canonical_component(by_revision[pin.item_revision_id], pin)
            for pin in pins
        )
    ):
        raise ApiError(
            409,
            "ITEM_DB_SIMILARITY_RESULT_STALE",
            "Item navigation unavailable",
            "An exact search candidate is no longer available in the current Graph.",
        )
    return tuple(by_revision[pin.item_revision_id] for pin in pins)
