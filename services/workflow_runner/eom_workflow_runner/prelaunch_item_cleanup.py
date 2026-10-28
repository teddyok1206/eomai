"""Owner application adapter for the exact approved prelaunch Item cleanup."""

from __future__ import annotations

from contextlib import AbstractContextManager

from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction, reset_rows_digest
from eom_orchestrator.metadata_reset_transaction import reset_delete as _delete
from eom_orchestrator.metadata_reset_transaction import reset_read_value as _one
from eom_protocol.prelaunch_item_reset import (
    MIXED_GRAPHS,
    WorkflowResetObservation,
)


def select_prelaunch_workflows(
    cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
) -> tuple[str, ...]:
    cursor.require_owner(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT DISTINCT workflow_id FROM item_revisions WHERE item_id=ANY(%s) UNION "
            "SELECT workflow_id FROM resolved_execution_plans WHERE "
            "graph_snapshot_revision_id=ANY(%s) UNION SELECT workflow_id FROM "
            "knowledge_analysis_runs WHERE item_id=ANY(%s) AND workflow_id IS NOT NULL"
        ),
        (list(item_ids), list(MIXED_GRAPHS), list(item_ids)),
    )
    workflow_ids = tuple(sorted(str(row[0]) for row in cursor.fetchall()))
    if len(workflow_ids) != 170:
        raise RuntimeError("AI_ITEM_RESET_WORKFLOW_TARGET_DRIFT")
    nonterminal_count = _one(
        cursor,
        (
            "SELECT count(*) FROM workflow_instances WHERE workflow_id=ANY(%s) AND state "
            "NOT IN ('COMPLETED','FAILED','CANCELLED')"
        ),
        (list(workflow_ids),),
    )
    if nonterminal_count != 0:
        raise RuntimeError("AI_ITEM_RESET_NONTERMINAL_WORKFLOW")
    return workflow_ids


def select_native_graph_derivations(cursor: MetadataResetTransaction) -> tuple[str, ...]:
    """Old Graph INDEX/QUERY derivations, not another source corpus.

    Deleting a quiescent prelaunch execution is not changing its outcome. Its
    original state remains in the recovery dump; no FAILED row is made successful.
    """
    cursor.require_owner(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT workflow_id,definition_key FROM workflow_instances WHERE "
            "definition_key IN "
            "('local-embedding-index','local-embedding-reference-query') AND "
            "jsonb_path_exists(request_payload, '$.**.graph_snapshot_revision_id ? (@ == "
            "$first || @ == $second)', "
            "jsonb_build_object('first',%s::text,'second',%s::text)) ORDER BY workflow_id"
        ),
        MIXED_GRAPHS,
    )
    rows = cursor.fetchall()
    if any(
        (
            definition not in {"local-embedding-index", "local-embedding-reference-query"}
            for _, definition in rows
        )
    ):
        raise RuntimeError("AI_ITEM_RESET_UNAPPROVED_NATIVE_SCOPE")
    return tuple(str(row[0]) for row in rows)


def delete_prelaunch_workflows(
    cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...]
) -> None:
    cursor.require_component(OWNED_TABLES)
    ids = list(workflow_ids)
    _delete(
        cursor,
        "resolved_execution_plans_deleted",
        "DELETE FROM resolved_execution_plans WHERE workflow_id=ANY(%s)",
        (ids,),
    )
    _delete(
        cursor,
        "workflow_instances_deleted",
        "DELETE FROM workflow_instances WHERE workflow_id=ANY(%s)",
        (ids,),
    )


OWNED_TABLES = (
    "resolved_execution_plan_steps",
    "resolved_execution_plans",
    "workflow_commands",
    "workflow_events",
    "workflow_instances",
    "workflow_step_runs",
)
OWNED_TRIGGERS = (
    ("resolved_execution_plans", "resolved_execution_plans_immutable"),
    ("resolved_execution_plan_steps", "resolved_execution_plan_steps_immutable"),
    ("workflow_instances", "workflow_instance_snapshot_immutable"),
    ("workflow_instances", "workflow_instance_private_query_origin_immutable"),
)


def prelaunch_mutations(cursor: MetadataResetTransaction) -> AbstractContextManager[None]:
    return cursor.owner_mutations(OWNED_TABLES, OWNED_TRIGGERS)


def observe_prelaunch_workflows(
    cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
) -> WorkflowResetObservation:
    ids = tuple(
        sorted(
            set(select_prelaunch_workflows(cursor, item_ids))
            | set(select_native_graph_derivations(cursor))
        )
    )
    selected = (list(ids),)
    digest = reset_rows_digest(
        cursor,
        (
            (
                (
                    "SELECT to_jsonb(t)::text FROM workflow_instances t WHERE "
                    "workflow_id=ANY(%s) ORDER BY workflow_id"
                ),
                selected,
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM workflow_commands t WHERE workflow_id=ANY(%s) "
                    "ORDER BY command_id"
                ),
                selected,
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM workflow_step_runs t WHERE "
                    "workflow_id=ANY(%s) ORDER BY step_run_id"
                ),
                selected,
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM resolved_execution_plans t WHERE "
                    "workflow_id=ANY(%s) ORDER BY workflow_id"
                ),
                selected,
            ),
        ),
    )
    return WorkflowResetObservation(ids, digest)


def delete_prelaunch_graph_plans(cursor: MetadataResetTransaction) -> None:
    cursor.require_component(OWNED_TABLES)
    _delete(
        cursor,
        "mixed_graph_resolved_plans_deleted",
        "DELETE FROM resolved_execution_plans WHERE graph_snapshot_revision_id=ANY(%s)",
        (list(MIXED_GRAPHS),),
    )


def verify_prelaunch_workflow_absence(
    cursor: MetadataResetTransaction, ids: tuple[str, ...]
) -> None:
    cursor.require_owner(OWNED_TABLES)
    if (
        _one(
            cursor,
            "SELECT count(*) FROM workflow_instances WHERE workflow_id=ANY(%s)",
            (list(ids),),
        )
        != 0
    ):
        raise ValueError("ITEM_RESET_WORKFLOWS_REMAIN")
    cursor.execute(
        (
            "SELECT count(*) FROM workflow_instances WHERE "
            "jsonb_path_exists(initial_request,'$.**.graph_snapshot_revision_id ? (@ == "
            "$first || @ == "
            "$second)',jsonb_build_object('first',%s::text,'second',%s::text))"
        ),
        MIXED_GRAPHS,
    )
    if cursor.fetchone() != (0,):
        raise ValueError("ITEM_RESET_UNHANDLED_GRAPH_WORKFLOW")
