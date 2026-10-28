"""Owner application adapter for the exact approved prelaunch Item cleanup."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction, reset_rows_digest
from eom_orchestrator.metadata_reset_transaction import reset_delete as _delete
from eom_orchestrator.metadata_reset_transaction import reset_read_value as _one
from eom_protocol.prelaunch_item_reset import (
    ASSEMBLY_ID,
    ASSEMBLY_REVISION,
    BASE_GRAPH,
    FORM_ID,
    KEEP_ITEM_ID,
    MIXED_GRAPHS,
    TARGET_SHA256,
    CatalogResetObservation,
    ResetGraphPin,
)
from psycopg import sql


def select_prelaunch_items(cursor: MetadataResetTransaction) -> tuple[str, ...]:
    cursor.require_owner(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT DISTINCT r.item_id FROM item_revisions r JOIN workflow_instances w "
            "ON w.workflow_id=r.workflow_id WHERE w.definition_key=%s AND r.item_id<>%s "
            "ORDER BY r.item_id"
        ),
        ("generic-item-development", KEEP_ITEM_ID),
    )
    item_ids = tuple(str(row[0]) for row in cursor.fetchall())
    digest = hashlib.sha256(
        json.dumps(item_ids, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    if len(item_ids) != 110 or digest != TARGET_SHA256:
        raise RuntimeError("AI_ITEM_RESET_TARGET_DRIFT")
    return item_ids


def validate_prelaunch_catalog(cursor: MetadataResetTransaction) -> None:
    cursor.require_owner(OWNED_TABLES)
    current = _one(
        cursor,
        (
            "SELECT current_graph_snapshot_revision_id FROM knowledge_corpora WHERE "
            "corpus_key=%s FOR UPDATE"
        ),
        ("integrated-science-textbooks",),
    )
    if current != MIXED_GRAPHS[1]:
        raise RuntimeError("AI_ITEM_RESET_GRAPH_DRIFT")
    cursor.execute(
        (
            "SELECT source_class,count(DISTINCT source_revision_id) FROM "
            "knowledge_node_source_pointers WHERE graph_snapshot_revision_id=%s GROUP BY "
            "source_class"
        ),
        (BASE_GRAPH,),
    )
    counts = {str(key): int(str(count)) for key, count in cursor.fetchall()}
    if counts != {"PAST_EXAM": 520, "TEXTBOOK": 10}:
        raise RuntimeError("AI_ITEM_RESET_BASE_GRAPH_INVALID")
    cursor.execute(
        (
            "SELECT w.workflow_id,w.state FROM resolved_execution_plans p JOIN "
            "workflow_instances w ON w.workflow_id=p.workflow_id WHERE "
            "p.graph_snapshot_revision_id=ANY(%s)"
        ),
        (list(MIXED_GRAPHS),),
    )
    pinned_plans = cursor.fetchall()
    sample_plan_count = _one(
        cursor,
        (
            "SELECT count(*) FROM resolved_execution_plans p JOIN item_revisions r ON "
            "r.workflow_id=p.workflow_id WHERE p.graph_snapshot_revision_id=ANY(%s) AND "
            "r.item_id=%s"
        ),
        (list(MIXED_GRAPHS), KEEP_ITEM_ID),
    )
    if (
        len(pinned_plans) != 60
        or any(
            (str(state) not in {"COMPLETED", "FAILED", "CANCELLED"} for _, state in pinned_plans)
        )
        or sample_plan_count != 0
    ):
        raise RuntimeError("AI_ITEM_RESET_PINNED_PLAN_DRIFT")
    cursor.execute(
        (
            "SELECT count(*),count(*) FILTER (WHERE item_id=ANY(%s)) FROM "
            "assessment_item_placements WHERE assessment_assembly_revision_id=%s"
        ),
        (list(select_prelaunch_items(cursor)), ASSEMBLY_REVISION),
    )
    if cursor.fetchone() != (25, 25):
        raise RuntimeError("AI_ITEM_RESET_ASSEMBLY_MIXED")


def delete_prelaunch_retrievals(cursor: MetadataResetTransaction) -> None:
    cursor.require_component(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT retrieval_request_id FROM education_retrieval_requests WHERE "
            "graph_snapshot_revision_id=ANY(%s)"
        ),
        (list(MIXED_GRAPHS),),
    )
    request_ids = [str(row[0]) for row in cursor.fetchall()]
    if len(request_ids) != 66:
        raise RuntimeError("AI_ITEM_RESET_RETRIEVAL_DRIFT")
    _delete(
        cursor,
        "evidence_bundle_current_cleared",
        ("UPDATE evidence_bundles SET current_revision_id=NULL WHERE retrieval_request_id=ANY(%s)"),
        (request_ids,),
    )
    _delete(
        cursor,
        "evidence_bundle_revisions_deleted",
        "DELETE FROM evidence_bundle_revisions WHERE retrieval_request_id=ANY(%s)",
        (request_ids,),
    )
    _delete(
        cursor,
        "evidence_bundles_deleted",
        "DELETE FROM evidence_bundles WHERE retrieval_request_id=ANY(%s)",
        (request_ids,),
    )
    _delete(
        cursor,
        "retrieval_requests_deleted",
        "DELETE FROM education_retrieval_requests WHERE retrieval_request_id=ANY(%s)",
        (request_ids,),
    )


def delete_prelaunch_indexes(cursor: MetadataResetTransaction) -> None:
    cursor.require_component(OWNED_TABLES)
    cursor.execute(
        (
            "SELECT DISTINCT index_id FROM embedding_index_revisions WHERE "
            "graph_snapshot_revision_id=ANY(%s)"
        ),
        (list(MIXED_GRAPHS),),
    )
    index_ids = [str(row[0]) for row in cursor.fetchall()]
    if (
        index_ids
        and _one(
            cursor,
            "SELECT count(*) FROM embedding_index_revisions WHERE index_id=ANY(%s) "
            "AND graph_snapshot_revision_id<>ALL(%s)",
            (index_ids, list(MIXED_GRAPHS)),
        )
        != 0
    ):
        raise ValueError("ITEM_RESET_SHARED_INDEX_NAMESPACE")
    _delete(
        cursor,
        "embedding_bindings_deleted",
        "DELETE FROM embedding_source_bindings WHERE graph_snapshot_revision_id=ANY(%s)",
        (list(MIXED_GRAPHS),),
    )
    if index_ids:
        _delete(
            cursor,
            "embedding_index_heads_cleared",
            (
                "UPDATE embedding_indexes SET current_index_revision_id=NULL,lock_version=1 "
                "WHERE index_id=ANY(%s)"
            ),
            (index_ids,),
        )
        cursor.execute(
            (
                "SELECT index_revision_id FROM embedding_index_revisions WHERE "
                "index_id=ANY(%s) ORDER BY index_id,revision_number DESC"
            ),
            (index_ids,),
        )
        revision_ids = [str(row[0]) for row in cursor.fetchall()]
        for revision_id in revision_ids:
            cursor.execute(
                "DELETE FROM embedding_index_revisions WHERE index_revision_id=%s", (revision_id,)
            )
        cursor.record("embedding_index_revisions_deleted", len(revision_ids))
        _delete(
            cursor,
            "embedding_indexes_deleted",
            "DELETE FROM embedding_indexes WHERE index_id=ANY(%s)",
            (index_ids,),
        )


def delete_prelaunch_graphs(cursor: MetadataResetTransaction) -> None:
    cursor.require_component(OWNED_TABLES)
    base_corpus_revision = _one(
        cursor,
        (
            "SELECT corpus_revision_id FROM knowledge_graph_snapshots WHERE "
            "graph_snapshot_revision_id=%s"
        ),
        (BASE_GRAPH,),
    )
    cursor.execute(
        (
            "SELECT corpus_revision_id FROM knowledge_graph_snapshots WHERE "
            "graph_snapshot_revision_id=ANY(%s) ORDER BY revision_number"
        ),
        (list(MIXED_GRAPHS),),
    )
    mixed_corpus_revisions = [str(row[0]) for row in cursor.fetchall()]
    if len(mixed_corpus_revisions) != 2:
        raise RuntimeError("AI_ITEM_RESET_CORPUS_REVISION_DRIFT")
    _delete(
        cursor,
        "corpus_head_rewound",
        (
            "UPDATE knowledge_corpora SET current_graph_snapshot_revision_id=%s, "
            "current_corpus_revision_id=%s,lock_version=lock_version+1 WHERE "
            "corpus_key=%s AND current_graph_snapshot_revision_id=%s"
        ),
        (BASE_GRAPH, base_corpus_revision, "integrated-science-textbooks", MIXED_GRAPHS[1]),
    )
    _delete(
        cursor,
        "graph_publications_deleted",
        "DELETE FROM knowledge_graph_publications WHERE graph_snapshot_revision_id=ANY(%s)",
        (list(MIXED_GRAPHS),),
    )
    for graph_id in reversed(MIXED_GRAPHS):
        _delete(
            cursor,
            "graph_snapshot_deleted",
            "DELETE FROM knowledge_graph_snapshots WHERE graph_snapshot_revision_id=%s",
            (graph_id,),
        )
    for corpus_revision_id in reversed(mixed_corpus_revisions):
        _delete(
            cursor,
            "corpus_revision_deleted",
            "DELETE FROM knowledge_corpus_revisions WHERE corpus_revision_id=%s",
            (corpus_revision_id,),
        )


def validate_retained_catalog(cursor: MetadataResetTransaction) -> None:
    cursor.require_owner(OWNED_TABLES)
    current = _one(
        cursor,
        (
            "SELECT current_graph_snapshot_revision_id FROM knowledge_corpora WHERE "
            "corpus_key=%s FOR UPDATE"
        ),
        ("integrated-science-textbooks",),
    )
    if current != BASE_GRAPH:
        raise RuntimeError("AI_ITEM_RESET_ITEM_PHASE_GRAPH_INVALID")
    cursor.execute(
        (
            "SELECT source_class,count(DISTINCT source_revision_id) FROM "
            "knowledge_node_source_pointers WHERE graph_snapshot_revision_id=%s GROUP BY "
            "source_class"
        ),
        (BASE_GRAPH,),
    )
    counts = {str(key): int(str(count)) for key, count in cursor.fetchall()}
    if counts != {"PAST_EXAM": 520, "TEXTBOOK": 10}:
        raise RuntimeError("AI_ITEM_RESET_ITEM_PHASE_BASE_INVALID")
    if _one(cursor, "SELECT count(*) FROM item_revisions WHERE item_id=%s", (KEEP_ITEM_ID,)) != 1:
        raise RuntimeError("AI_ITEM_RESET_SAMPLE_MISSING")


def delete_prelaunch_items(cursor: MetadataResetTransaction) -> None:
    cursor.require_component(OWNED_TABLES)
    item_ids = list(select_prelaunch_items(cursor))
    cursor.execute("SELECT item_revision_id FROM item_revisions WHERE item_id=ANY(%s)", (item_ids,))
    revision_ids = [str(row[0]) for row in cursor.fetchall()]
    if len(revision_ids) != 111:
        raise RuntimeError("AI_ITEM_RESET_REVISION_DRIFT")
    _delete(
        cursor,
        "form_head_cleared",
        "UPDATE assessment_forms SET current_revision_id=NULL WHERE assessment_form_id=%s",
        (FORM_ID,),
    )
    _delete(
        cursor,
        "assembly_head_cleared",
        (
            "UPDATE assessment_assemblies SET current_revision_id=NULL WHERE "
            "assessment_assembly_id=%s"
        ),
        (ASSEMBLY_ID,),
    )
    _delete(
        cursor,
        "form_revisions_deleted",
        "DELETE FROM assessment_form_revisions WHERE assessment_form_id=%s",
        (FORM_ID,),
    )
    _delete(
        cursor,
        "assembly_placements_deleted",
        "DELETE FROM assessment_item_placements WHERE assessment_assembly_revision_id=%s",
        (ASSEMBLY_REVISION,),
    )
    _delete(
        cursor,
        "assembly_revisions_deleted",
        "DELETE FROM assessment_assembly_revisions WHERE assessment_assembly_id=%s",
        (ASSEMBLY_ID,),
    )
    _delete(
        cursor,
        "assemblies_deleted",
        "DELETE FROM assessment_assemblies WHERE assessment_assembly_id=%s",
        (ASSEMBLY_ID,),
    )
    _delete(
        cursor,
        "forms_deleted",
        "DELETE FROM assessment_forms WHERE assessment_form_id=%s",
        (FORM_ID,),
    )
    _delete(
        cursor,
        "item_reviews_deleted",
        "DELETE FROM item_review_records WHERE item_revision_id=ANY(%s)",
        (revision_ids,),
    )
    _delete(
        cursor,
        "item_relationships_deleted",
        ("DELETE FROM item_relationships WHERE source_item_id=ANY(%s) OR target_item_id=ANY(%s)"),
        (item_ids, item_ids),
    )
    _delete(
        cursor, "item_events_deleted", "DELETE FROM item_events WHERE item_id=ANY(%s)", (item_ids,)
    )
    _delete(
        cursor,
        "item_components_deleted",
        "DELETE FROM item_components WHERE item_revision_id=ANY(%s)",
        (revision_ids,),
    )
    _delete(
        cursor,
        "item_metadata_snapshots_deleted",
        "DELETE FROM item_metadata_snapshots WHERE item_revision_id=ANY(%s)",
        (revision_ids,),
    )
    _delete(
        cursor,
        "item_provenance_deleted",
        "DELETE FROM item_provenance WHERE item_revision_id=ANY(%s)",
        (revision_ids,),
    )
    _delete(
        cursor,
        "item_heads_cleared",
        "UPDATE items SET current_revision_id=NULL WHERE item_id=ANY(%s)",
        (item_ids,),
    )
    _delete(
        cursor,
        "item_revisions_deleted",
        "DELETE FROM item_revisions WHERE item_revision_id=ANY(%s)",
        (revision_ids,),
    )
    _delete(cursor, "items_deleted", "DELETE FROM items WHERE item_id=ANY(%s)", (item_ids,))
    if _one(cursor, "SELECT count(*) FROM items WHERE item_id=ANY(%s)", (item_ids,)) != 0:
        raise RuntimeError("AI_ITEM_RESET_ITEMS_REMAIN")


def verify_retained_catalog(cursor: MetadataResetTransaction) -> None:
    cursor.require_owner(OWNED_TABLES)
    validate_retained_catalog(cursor)
    checks = (
        (
            "generated_items_remaining",
            (
                "SELECT count(DISTINCT r.item_id) FROM item_revisions r JOIN "
                "workflow_instances w ON w.workflow_id=r.workflow_id WHERE "
                "w.definition_key=%s AND r.item_id<>%s"
            ),
            ("generic-item-development", KEEP_ITEM_ID),
            0,
        ),
        (
            "mixed_graphs_remaining",
            (
                "SELECT count(*) FROM knowledge_graph_snapshots WHERE "
                "graph_snapshot_revision_id=ANY(%s)"
            ),
            (list(MIXED_GRAPHS),),
            0,
        ),
        (
            "mixed_graph_pinned_plans_remaining",
            (
                "SELECT count(*) FROM resolved_execution_plans WHERE "
                "graph_snapshot_revision_id=ANY(%s)"
            ),
            (list(MIXED_GRAPHS),),
            0,
        ),
        (
            "deleted_assembly_placements_remaining",
            (
                "SELECT count(*) FROM assessment_item_placements WHERE "
                "assessment_assembly_revision_id=%s"
            ),
            (ASSEMBLY_REVISION,),
            0,
        ),
        (
            "external_import_sources_preserved",
            "SELECT count(*) FROM external_item_sources",
            (),
            1297,
        ),
        (
            "legacy_item_revisions_preserved",
            (
                "SELECT count(DISTINCT r.item_id) FROM item_revisions r JOIN "
                "workflow_instances w ON w.workflow_id=r.workflow_id WHERE "
                "w.definition_key=%s"
            ),
            ("legacy-item-extraction",),
            757,
        ),
    )
    for label, query, params, expected in checks:
        actual = _one(cursor, query, params)
        if actual != expected:
            raise RuntimeError(f"AI_ITEM_RESET_POSTCONDITION_FAILED:{label}")
        cursor.record(label, int(str(actual)))


def delete_prelaunch_document_reviews(
    cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...]
) -> None:
    cursor.require_component(OWNED_TABLES)
    ids = list(workflow_ids)
    _delete(
        cursor,
        "document_review_annotation_outputs_deleted",
        (
            "DELETE FROM document_review_pdf_annotation_outputs WHERE annotation_id IN "
            "(SELECT annotation_id FROM document_review_pdf_annotations WHERE "
            "workflow_id=ANY(%s))"
        ),
        (ids,),
    )
    _delete(
        cursor,
        "document_review_annotations_deleted",
        "DELETE FROM document_review_pdf_annotations WHERE workflow_id=ANY(%s)",
        (ids,),
    )
    _delete(
        cursor,
        "document_review_corrections_deleted",
        "DELETE FROM document_review_hwpx_corrections WHERE workflow_id=ANY(%s)",
        (ids,),
    )
    _delete(
        cursor,
        "document_review_set_members_deleted",
        (
            "DELETE FROM document_review_set_members WHERE review_set_id IN (SELECT "
            "review_set_id FROM document_review_sets WHERE workflow_id=ANY(%s))"
        ),
        (ids,),
    )
    _delete(
        cursor,
        "document_review_sets_deleted",
        "DELETE FROM document_review_sets WHERE workflow_id=ANY(%s)",
        (ids,),
    )
    if (
        _one(
            cursor,
            "SELECT count(*) FROM pdf_document_review_upload_intents WHERE workflow_id=ANY(%s)",
            (ids,),
        )
        != 0
    ):
        raise ValueError("ITEM_RESET_API_OWNED_DEPENDENCY")


OWNED_TABLES = (
    "assessment_assemblies",
    "assessment_assembly_revisions",
    "assessment_form_revisions",
    "assessment_forms",
    "assessment_item_placements",
    "document_review_hwpx_corrections",
    "document_review_pdf_annotation_outputs",
    "document_review_pdf_annotations",
    "document_review_set_members",
    "document_review_sets",
    "education_retrieval_requests",
    "embedding_index_revisions",
    "embedding_indexes",
    "embedding_source_bindings",
    "evidence_bundle_entries",
    "evidence_bundle_revisions",
    "evidence_bundles",
    "item_components",
    "item_events",
    "item_metadata_snapshots",
    "item_provenance",
    "item_relationships",
    "item_review_records",
    "item_revisions",
    "items",
    "knowledge_corpora",
    "knowledge_corpus_revisions",
    "knowledge_edge_source_pointers",
    "knowledge_graph_publications",
    "knowledge_graph_snapshots",
    "knowledge_node_source_pointers",
)
OWNED_TRIGGERS = (
    ("assessment_assembly_revisions", "assessment_assembly_revisions_immutable"),
    ("assessment_form_revisions", "assessment_form_revisions_immutable"),
    ("assessment_item_placements", "assessment_item_placements_immutable"),
    ("education_retrieval_requests", "education_retrieval_requests_immutable"),
    ("embedding_indexes", "embedding_indexes_identity_immutable"),
    ("embedding_index_revisions", "embedding_index_revisions_immutable"),
    ("embedding_source_bindings", "embedding_source_bindings_immutable"),
    ("evidence_bundle_entries", "evidence_bundle_entries_immutable"),
    ("evidence_bundle_revisions", "evidence_bundle_revisions_immutable"),
    ("item_components", "item_components_immutable"),
    ("item_metadata_snapshots", "item_metadata_snapshots_immutable"),
    ("item_provenance", "item_provenance_immutable"),
    ("item_revisions", "item_revisions_immutable"),
)


def prelaunch_mutations(cursor: MetadataResetTransaction) -> AbstractContextManager[None]:
    return cursor.owner_mutations(OWNED_TABLES, OWNED_TRIGGERS)


@contextmanager
def prelaunch_lookup_indexes(cursor: MetadataResetTransaction) -> Iterator[None]:
    """Transaction-local maintenance optimization, not a persistent schema release."""
    cursor.require_component(OWNED_TABLES)
    indexes = (
        ("eom_prelaunch_node_artifact_lookup", "knowledge_node_source_pointers"),
        ("eom_prelaunch_edge_artifact_lookup", "knowledge_edge_source_pointers"),
    )
    for name, table in indexes:
        cursor.execute("SELECT to_regclass(%s)", (f"app.{name}",))
        if cursor.fetchone() != (None,):
            raise ValueError("ITEM_RESET_SCRATCH_INDEX_CONFLICT")
        cursor.execute(
            sql.SQL("CREATE INDEX {} ON {} (source_artifact_id)").format(
                sql.Identifier(name), sql.Identifier("app", table)
            )
        )
    try:
        yield
    except BaseException:
        raise  # All DDL and data are rolled back by the application root.
    else:
        for name, _table in reversed(indexes):
            cursor.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier("app", name)))


def protected_catalog_digest(cursor: MetadataResetTransaction, item_ids: tuple[str, ...]) -> str:
    cursor.require_owner(OWNED_TABLES)
    selected = (list(item_ids),)
    return reset_rows_digest(
        cursor,
        (
            (
                "SELECT to_jsonb(t)::text FROM items t WHERE item_id<>ALL(%s) ORDER BY item_id",
                selected,
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM item_revisions t WHERE item_id<>ALL(%s) ORDER "
                    "BY item_revision_id"
                ),
                selected,
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM item_components t WHERE item_revision_id IN "
                    "(SELECT item_revision_id FROM item_revisions WHERE item_id<>ALL(%s)) ORDER "
                    "BY item_component_id"
                ),
                selected,
            ),
            ("SELECT to_jsonb(t)::text FROM external_item_sources t ORDER BY source_id", ()),
            (
                (
                    "SELECT to_jsonb(t)::text FROM external_item_source_revisions t ORDER BY "
                    "revision_id"
                ),
                (),
            ),
            ("SELECT to_jsonb(t)::text FROM educational_documents t ORDER BY document_id", ()),
            (
                (
                    "SELECT to_jsonb(t)::text FROM educational_document_revisions t ORDER BY "
                    "document_revision_id"
                ),
                (),
            ),
            (
                (
                    "SELECT to_jsonb(t)::text FROM knowledge_graph_snapshots t WHERE "
                    "graph_snapshot_revision_id=%s"
                ),
                (BASE_GRAPH,),
            ),
            (
                (
                    "SELECT "
                    "jsonb_build_array(source_class,source_revision_id,source_sha256)::text FROM "
                    "knowledge_node_source_pointers WHERE graph_snapshot_revision_id=%s GROUP BY "
                    "source_class,source_revision_id,source_sha256 ORDER BY "
                    "source_class,source_revision_id,source_sha256"
                ),
                (BASE_GRAPH,),
            ),
        ),
    )


def observe_prelaunch_catalog(cursor: MetadataResetTransaction) -> CatalogResetObservation:
    validate_prelaunch_catalog(cursor)
    items = select_prelaunch_items(cursor)
    cursor.execute(
        (
            "SELECT item_revision_id FROM item_revisions WHERE item_id=ANY(%s) ORDER BY "
            "item_revision_id"
        ),
        (list(items),),
    )
    revisions = tuple(str(row[0]) for row in cursor.fetchall())
    cursor.execute(
        (
            "SELECT graph_snapshot_revision_id,manifest_sha256 FROM "
            "knowledge_graph_snapshots WHERE graph_snapshot_revision_id=ANY(%s) ORDER BY "
            "graph_snapshot_revision_id"
        ),
        ([BASE_GRAPH, *MIXED_GRAPHS],),
    )
    pins = tuple(
        ResetGraphPin(revision_id=str(row[0]), sha256=str(row[1])) for row in cursor.fetchall()
    )
    queries = (
        (
            "SELECT to_jsonb(t)::text FROM items t WHERE item_id=ANY(%s) ORDER BY item_id",
            (list(items),),
        ),
        (
            (
                "SELECT to_jsonb(t)::text FROM item_revisions t WHERE item_id=ANY(%s) ORDER "
                "BY item_revision_id"
            ),
            (list(items),),
        ),
        (
            (
                "SELECT to_jsonb(t)::text FROM education_retrieval_requests t WHERE "
                "graph_snapshot_revision_id=ANY(%s) ORDER BY retrieval_request_id"
            ),
            (list(MIXED_GRAPHS),),
        ),
        (
            (
                "SELECT to_jsonb(t)::text FROM embedding_index_revisions t WHERE "
                "graph_snapshot_revision_id=ANY(%s) ORDER BY index_revision_id"
            ),
            (list(MIXED_GRAPHS),),
        ),
        (
            (
                "SELECT to_jsonb(t)::text FROM embedding_source_bindings t WHERE "
                "graph_snapshot_revision_id=ANY(%s) ORDER BY binding_sha256"
            ),
            (list(MIXED_GRAPHS),),
        ),
    )
    return CatalogResetObservation(
        items,
        revisions,
        pins,
        reset_rows_digest(cursor, queries),
        protected_catalog_digest(cursor, items),
    )


def deleted_prelaunch_targets_absent(
    cursor: MetadataResetTransaction, item_ids: tuple[str, ...], revisions: tuple[str, ...]
) -> bool:
    cursor.require_owner(OWNED_TABLES)
    return (
        _one(cursor, "SELECT count(*) FROM items WHERE item_id=ANY(%s)", (list(item_ids),)) == 0
        and _one(
            cursor,
            "SELECT count(*) FROM item_revisions WHERE item_revision_id=ANY(%s)",
            (list(revisions),),
        )
        == 0
        and _one(
            cursor,
            (
                "SELECT count(*) FROM knowledge_graph_snapshots WHERE "
                "graph_snapshot_revision_id=ANY(%s)"
            ),
            (list(MIXED_GRAPHS),),
        )
        == 0
    )
