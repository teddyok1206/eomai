"""Owner application adapter for the exact approved prelaunch Item cleanup."""

from __future__ import annotations

from contextlib import AbstractContextManager

from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction, reset_rows_digest
from eom_orchestrator.metadata_reset_transaction import reset_delete as _delete
from eom_protocol.prelaunch_item_reset import (
    ASSEMBLY_REVISION,
    BuildResetObservation,
)


def delete_prelaunch_builds(cursor: MetadataResetTransaction, item_ids: tuple[str, ...]) -> None:
    cursor.require_component(OWNED_TABLES)
    _delete(
        cursor,
        "hwpx_assembly_builds_deleted",
        ("DELETE FROM hwpx_assessment_assembly_builds WHERE assessment_assembly_revision_id=%s"),
        (ASSEMBLY_REVISION,),
    )
    _delete(
        cursor,
        "hwpx_item_builds_deleted",
        "DELETE FROM hwpx_application_builds WHERE item_id=ANY(%s)",
        (list(item_ids),),
    )


OWNED_TABLES = ("hwpx_application_builds", "hwpx_assessment_assembly_builds")
OWNED_TRIGGERS: tuple[tuple[str, str], ...] = ()


def prelaunch_mutations(cursor: MetadataResetTransaction) -> AbstractContextManager[None]:
    return cursor.owner_mutations(OWNED_TABLES, OWNED_TRIGGERS)


def protected_build_digest(cursor: MetadataResetTransaction, item_ids: tuple[str, ...]) -> str:
    cursor.require_owner(OWNED_TABLES)
    return reset_rows_digest(
        cursor,
        (
            (
                (
                    "SELECT to_jsonb(t)::text FROM hwpx_application_builds t WHERE "
                    "item_id<>ALL(%s) ORDER BY build_id"
                ),
                (list(item_ids),),
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM hwpx_assessment_assembly_builds t WHERE "
                    "assessment_assembly_revision_id<>%s ORDER BY build_id"
                ),
                (ASSEMBLY_REVISION,),
            ),
        ),
    )


def observe_prelaunch_builds(
    cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
) -> BuildResetObservation:
    cursor.require_owner(OWNED_TABLES)
    baseline = reset_rows_digest(
        cursor,
        (
            (
                (
                    "SELECT to_jsonb(t)::text FROM hwpx_application_builds t WHERE "
                    "item_id=ANY(%s) ORDER BY build_id"
                ),
                (list(item_ids),),
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM hwpx_assessment_assembly_builds t WHERE "
                    "assessment_assembly_revision_id=%s ORDER BY build_id"
                ),
                (ASSEMBLY_REVISION,),
            ),
        ),
    )
    return BuildResetObservation(baseline, protected_build_digest(cursor, item_ids))
