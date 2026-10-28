"""Owner application adapter for the exact approved prelaunch Item cleanup."""

from __future__ import annotations

from contextlib import AbstractContextManager

from eom_protocol.prelaunch_item_reset import (
    MIXED_GRAPHS,
    ArtifactResetObservation,
)
from psycopg import sql

from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction, reset_rows_digest
from eom_orchestrator.metadata_reset_transaction import reset_delete as _delete
from eom_orchestrator.metadata_reset_transaction import reset_read_value as _one


def select_candidate_reset_jobs(
    cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...], item_ids: tuple[str, ...]
) -> tuple[str, ...]:
    cursor.require_owner(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT platform_job_id FROM workflow_step_runs WHERE workflow_id=ANY(%s) "
            "AND platform_job_id IS NOT NULL UNION SELECT job_id FROM jobs WHERE "
            "request::text LIKE ANY(%s) UNION SELECT a.job_id FROM artifact_revisions a "
            "JOIN item_revisions r ON r.manifest_artifact_revision_id=a.revision_id "
            "WHERE r.item_id=ANY(%s) ORDER BY 1"
        ),
        (list(workflow_ids), [f"%{graph}%" for graph in MIXED_GRAPHS], list(tuple(item_ids))),
    )
    return tuple(str(row[0]) for row in cursor.fetchall())


def reset_pointer_strings(value: object) -> set[str]:
    found: set[str] = set()
    stack = [value]
    while stack:
        part = stack.pop()
        if isinstance(part, str):
            found.add(part)
        elif isinstance(part, dict):
            found.update(key for key in part if isinstance(key, str))
            stack.extend(part.values())
        elif isinstance(part, list):
            stack.extend(part)
    return found


def protected_reset_dependencies(dependencies: dict[str, set[str]], external: set[str]) -> set[str]:
    if not external.issubset(dependencies) or any(
        not values.issubset(dependencies) for values in dependencies.values()
    ):
        raise ValueError("ITEM_RESET_DEPENDENCY_SCOPE_INVALID")
    protected = set(external)
    pending = list(protected)
    while pending:
        for dependency in dependencies[pending.pop()] - protected:
            protected.add(dependency)
            pending.append(dependency)
    return protected


def delete_exclusive_reset_jobs(cursor: MetadataResetTransaction, job_ids: tuple[str, ...]) -> None:
    """Preserve shared FK/JSON dependencies; never unlink an Artifact directory.

    Candidate producer dependencies form an adjacency map. External references
    seed a protected set; its transitive closure retains the producer records
    needed by surviving content. This is O(rows + pointer edges), not a repeated
    candidate-by-payload scan. Large NAS payloads are not read or copied.
    """
    cursor.require_component(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT a.job_id,a.logical_artifact_id,r.revision_id FROM artifacts a LEFT "
            "JOIN artifact_revisions r ON r.logical_artifact_id=a.logical_artifact_id "
            "WHERE a.job_id=ANY(%s)"
        ),
        (list(job_ids),),
    )
    identity_owner = {job: job for job in job_ids}
    for job, artifact, revision in cursor.fetchall():
        identity_owner[str(artifact)] = str(job)
        if revision is not None:
            identity_owner[str(revision)] = str(job)
    protected: set[str] = set()
    dependencies: dict[str, set[str]] = {job: set() for job in job_ids}
    cursor.execute(
        "SELECT c.conrelid::regclass::text,c.confrelid::regclass::text,ARRAY(SELECT "
        "a.attname FROM unnest(c.conkey) WITH ORDINALITY k(attnum,n) JOIN "
        "pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY "
        "n),ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY "
        "k(attnum,n) JOIN pg_attribute a ON a.attrelid=c.confrelid AND "
        "a.attnum=k.attnum ORDER BY n) FROM pg_constraint c WHERE c.contype='f' AND "
        "c.confrelid IN "
        "('app.artifacts'::regclass,'app.artifact_revisions'::regclass,'app.jobs'::re"
        "gclass)"
    )
    for child, parent, child_columns, parent_columns in cursor.fetchall():
        table = str(child).rsplit(".", 1)[-1]
        if table in {"artifacts", "artifact_revisions", "job_events"}:
            continue
        if not isinstance(child_columns, list) or not isinstance(parent_columns, list):
            raise RuntimeError("AI_ITEM_RESET_INVALID_FK_METADATA")
        parent_table = str(parent).rsplit(".", 1)[-1]
        conditions = [
            sql.SQL("t.{}=p.{}").format(sql.Identifier(str(a)), sql.Identifier(str(b)))
            for a, b in zip(child_columns, parent_columns, strict=True)
        ]
        cursor.execute(
            sql.SQL(
                "SELECT DISTINCT p.job_id FROM app.{} p JOIN app.{} t ON {} WHERE p.job_id=ANY(%s)"
            ).format(
                sql.Identifier(parent_table),
                sql.Identifier(table),
                sql.SQL(" AND ").join(conditions),
            ),
            (list(job_ids),),
        )
        protected.update(str(row[0]) for row in cursor.fetchall())
    cursor.execute(
        "SELECT table_name,column_name FROM information_schema.columns WHERE "
        "table_schema='app' AND data_type IN ('json','jsonb') ORDER BY "
        "table_name,column_name"
    )
    json_columns = cursor.fetchall()
    for table_value, column_value in json_columns:
        table, column = (str(table_value), str(column_value))
        owner_column = (
            sql.Identifier("job_id")
            if table in {"jobs", "job_events", "artifact_revisions", "artifacts"}
            else sql.SQL("NULL")
        )
        cursor.execute(
            sql.SQL("SELECT {},{} FROM app.{} WHERE {} IS NOT NULL").format(
                owner_column,
                sql.Identifier(str(column)),
                sql.Identifier(str(table)),
                sql.Identifier(str(column)),
            )
        )
        while payload_rows := cursor.fetchmany(128):
            for producer, value in payload_rows:
                references = {
                    identity_owner[x] for x in reset_pointer_strings(value) if x in identity_owner
                }
                if producer in dependencies:
                    dependencies[str(producer)].update(references)
                else:
                    protected.update(references)
    protected = protected_reset_dependencies(dependencies, protected)
    exclusive = sorted(set(job_ids) - protected)
    cursor.record("candidate_jobs", len(job_ids))
    cursor.record("shared_jobs_preserved", len(protected))
    for label, query in (
        (
            "exclusive_artifact_revisions_deleted",
            "DELETE FROM artifact_revisions WHERE job_id=ANY(%s)",
        ),
        ("exclusive_artifacts_deleted", "DELETE FROM artifacts WHERE job_id=ANY(%s)"),
        ("exclusive_job_events_deleted", "DELETE FROM job_events WHERE job_id=ANY(%s)"),
        ("exclusive_jobs_deleted", "DELETE FROM jobs WHERE job_id=ANY(%s)"),
    ):
        _delete(cursor, label, query, (exclusive,))


def delete_prelaunch_leases(
    cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...]
) -> None:
    cursor.require_component(OWNED_TABLES)
    ids = list(workflow_ids)
    _delete(
        cursor,
        "worker_leases_deleted",
        "DELETE FROM worker_leases WHERE workflow_id=ANY(%s)",
        (ids,),
    )


OWNED_TABLES = (
    "artifact_revisions",
    "artifacts",
    "job_events",
    "jobs",
    "knowledge_analysis_runs",
    "worker_lease_events",
    "worker_leases",
)
OWNED_TRIGGERS = (
    ("artifacts", "artifacts_immutable"),
    ("artifact_revisions", "artifact_revisions_immutable"),
    ("worker_leases", "worker_leases_identity_immutable"),
    ("worker_lease_events", "worker_lease_events_immutable"),
)


def prelaunch_mutations(cursor: MetadataResetTransaction) -> AbstractContextManager[None]:
    return cursor.owner_mutations(OWNED_TABLES, OWNED_TRIGGERS)


def delete_prelaunch_analyses(cursor: MetadataResetTransaction, item_ids: tuple[str, ...]) -> None:
    cursor.require_component(OWNED_TABLES)
    _delete(
        cursor,
        "knowledge_analysis_runs_deleted",
        "DELETE FROM knowledge_analysis_runs WHERE item_id=ANY(%s)",
        (list(item_ids),),
    )


def protected_artifact_digest(cursor: MetadataResetTransaction, item_ids: tuple[str, ...]) -> str:
    cursor.require_owner(OWNED_TABLES)
    return reset_rows_digest(
        cursor,
        (
            ("SELECT to_jsonb(t)::text FROM embedding_encodings t ORDER BY encoding_sha256", ()),
            (
                (
                    "SELECT to_jsonb(t)::text FROM knowledge_analysis_runs t WHERE item_id IS "
                    "NULL OR item_id<>ALL(%s) ORDER BY analysis_run_id"
                ),
                (list(item_ids),),
            ),
        ),
    )


def observe_prelaunch_artifacts(
    cursor: MetadataResetTransaction, workflows: tuple[str, ...], items: tuple[str, ...]
) -> ArtifactResetObservation:
    jobs = select_candidate_reset_jobs(cursor, workflows, items)
    selected = (list(jobs),)
    digest = reset_rows_digest(
        cursor,
        (
            (
                (
                    "SELECT "
                    "jsonb_build_array(job_id,request_hash,status,logical_artifact_id,revision_id"
                    ")::text FROM jobs WHERE job_id=ANY(%s) ORDER BY job_id"
                ),
                selected,
            ),
            (
                (
                    "SELECT "
                    "jsonb_build_array(revision_id,logical_artifact_id,job_id,content_hash,conten"
                    "t_bytes,approved)::text FROM artifact_revisions WHERE job_id=ANY(%s) ORDER "
                    "BY revision_id"
                ),
                selected,
            ),
        ),
    )
    return ArtifactResetObservation(jobs, digest, protected_artifact_digest(cursor, items))


def reset_remaining_jobs(cursor: MetadataResetTransaction, ids: tuple[str, ...]) -> int:
    cursor.require_owner(OWNED_TABLES)
    return int(str(_one(cursor, "SELECT count(*) FROM jobs WHERE job_id=ANY(%s)", (list(ids),))))
