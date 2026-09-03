from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import eom_catalog_service.knowledge_analysis_batch_models
import eom_catalog_service.models  # noqa: F401
import eom_hwpx_manager.models  # noqa: F401
import eom_workflow_runner.models  # noqa: F401
import pytest
from eom_catalog_service import (  # noqa: F401
    item_origin_models,
    knowledge_graph_models,
    legacy_assessment_models,
    legacy_usage_models,
)
from eom_identifiers import content_sha256
from eom_orchestrator import (  # noqa: F401
    control_models,
    knowledge_analysis_models,
)
from eom_orchestrator.control_models import HELD_LEASE_PREDICATE
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    compute_control_document_hash,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.models import Base
from sqlalchemy import LargeBinary


def test_control_document_hash_omits_only_declared_digest() -> None:
    document = {
        "schema_version": "worker-capacity-policy/1.0",
        "capacity_policy_id": "capacity_" + "1" * 32,
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": datetime(2026, 8, 23, tzinfo=UTC),
    }
    expected = content_sha256(
        {
            "schema_version": document["schema_version"],
            "capacity_policy_id": document["capacity_policy_id"],
            "created_at": document["created_at"],
        }
    )
    assert compute_control_document_hash(document, "content_sha256") == expected
    with pytest.raises(ControlPlaneError) as exc_info:
        compute_control_document_hash(document, "missing")
    assert exc_info.value.code == "CONTROL_DOCUMENT_INVALID"


def test_cross_component_plan_evidence_is_frozen_and_pointer_only() -> None:
    evidence = ResolvedPlanDependencyEvidence(
        workflow_id="workflow_" + "1" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.4.0",
        workflow_definition_sha256="sha256:" + "2" * 64,
        workflow_role_schema_version="workflow-role/1.3.0",
        content_pack_release_id="packrel_" + "3" * 32,
        content_pack_sha256="sha256:" + "4" * 64,
    )
    assert evidence.graph_snapshot_revision_id is None
    with pytest.raises(AttributeError):
        evidence.workflow_id = "workflow_" + "5" * 32  # type: ignore[misc]


def test_control_tables_have_no_binary_or_secret_storage_columns() -> None:
    control_table_names = {
        "execution_bundles",
        "execution_bundle_revisions",
        "worker_capacity_policies",
        "worker_capacity_policy_revisions",
        "worker_capacity_pools",
        "worker_capacity_pool_roles",
        "worker_capacity_pool_slots",
        "execution_presets",
        "execution_preset_revisions",
        "execution_preset_role_policies",
        "execution_preset_evaluations",
        "resolved_execution_plans",
        "resolved_execution_plan_steps",
        "codex_auth_bindings",
        "codex_auth_health_events",
        "codex_capability_snapshots",
        "codex_capability_entries",
        "codex_control_commands",
        "worker_leases",
        "worker_lease_events",
    }
    assert control_table_names.issubset(Base.metadata.tables)
    forbidden = {"token", "secret", "credential", "password", "session", "auth_json", "nas_path"}
    for table_name in control_table_names:
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
        assert not forbidden.intersection(column.name for column in table.columns)


def test_lease_indexes_hold_capacity_while_reconciling() -> None:
    assert str(HELD_LEASE_PREDICATE) == "state IN ('ACTIVE','RECONCILING')"
    table = Base.metadata.tables["worker_leases"]
    indexes = {str(index.name): index for index in table.indexes if index.name is not None}
    assert indexes["uq_worker_lease_held_slot"].unique
    assert indexes["uq_worker_lease_held_job"].unique
    assert str(indexes["uq_worker_lease_held_slot"].dialect_options["postgresql"]["where"]) == (
        "state IN ('ACTIVE','RECONCILING')"
    )


def test_control_plane_migration_is_additive_and_reversible() -> None:
    source = Path("migrations/versions/20260823_0009_codex_control_plane.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | Sequence[str] | None = "20260821_0008"' in source
    assert "UPDATE workflow_instances" not in source
    assert "DELETE FROM workflow_instances" not in source
    assert "ALTER TABLE worker_slots" not in source
    assert "reject_control_plane_immutable_mutation" in source
    assert "validate_control_plane_current_revision" in source
    for table_name in (
        "execution_bundles",
        "execution_bundle_revisions",
        "worker_capacity_policy_revisions",
        "execution_presets",
        "resolved_execution_plans",
        "codex_auth_bindings",
        "codex_capability_snapshots",
        "worker_leases",
    ):
        assert f'"{table_name}"' in source


def test_mvp_control_plane_migration_is_additive_and_fail_closed() -> None:
    source = Path("migrations/versions/20260823_0010_codex_control_plane_mvp.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | Sequence[str] | None = "20260823_0009"' in source
    assert CURRENT_MIGRATION_REVISION == "20260903_0027"
    assert "execution_preset_evaluations" in source
    assert "codex_control_commands" in source
    assert "BEFORE UPDATE OR DELETE ON codex_control_commands" in source
    assert "execution_preset_evaluations_immutable" in source
    assert '"available_at"' in source
    assert '"ix_workflow_commands_claimable"' in source
    assert "UPDATE workflow_instances" not in source
    assert "DELETE FROM workflow_instances" not in source
    for permission in (
        "codex_account:read",
        "codex_account:manage",
        "execution_preset:read",
        "execution_preset:manage",
    ):
        assert permission in source


def test_multimodal_batch_migration_is_additive_and_keeps_legacy_pointers() -> None:
    source = Path("migrations/versions/20260827_0019_multimodal_knowledge_analysis.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260826_0018"' in source
    assert CURRENT_MIGRATION_REVISION == "20260903_0027"
    assert "textbook-analysis-bundle-manifest/1.0" in source
    assert "textbook-analysis-bundle-manifest/2.0" in source
    assert "drop_table" not in source
    assert "DELETE FROM" not in source


def test_codex_device_reauthentication_migration_is_additive_and_credential_free() -> None:
    source = Path(
        "migrations/versions/20260827_0020_codex_gui_device_reauthentication.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260827_0019"' in source
    assert CURRENT_MIGRATION_REVISION == "20260903_0027"
    assert "codex_auth_enrollments" in source
    assert "codex_auth_assignment_revisions" in source
    assert "codex_auth_assignment_revisions_immutable" in source
    assert "uq_codex_auth_enrollment_active_binding" in source
    assert "current_assignment_revision_id" in source
    assert "Codex authentication assignment pointer is invalid" in source
    assert "assignment.account_label = NEW.account_label" in source
    assert "login_unit_started_at" in source
    for forbidden in ("password", "access_token", "refresh_token", "auth_json"):
        assert forbidden not in source


def test_knowledge_analysis_continue_collect_migration_preserves_legacy_batches() -> None:
    source = Path(
        "migrations/versions/20260828_0021_knowledge_analysis_continue_collect.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260827_0020"' in source
    assert CURRENT_MIGRATION_REVISION == "20260903_0027"
    assert 'server_default="STOP_ON_FIRST_FAILURE"' in source
    assert "CONTINUE_AND_COLLECT" in source
    assert "DELETE FROM" not in source
    assert "UPDATE knowledge_analysis_batches" not in source


def test_bounded_parallel_capacity_migration_preserves_serial_history() -> None:
    source = Path(
        "migrations/versions/20260828_0022_bounded_parallel_knowledge_capacity.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260828_0021"' in source
    assert CURRENT_MIGRATION_REVISION == "20260903_0027"
    assert 'server_default="SERIAL"' in source
    assert 'server_default="1"' in source
    assert "max_active_knowledge_analysis BETWEEN 1 AND 2" in source
    assert "ix_knowledge_analysis_batch_active_range" in source
    assert "DELETE FROM" not in source
    assert "UPDATE knowledge_analysis_batches" not in source
    assert "bounded-parallel history prevents downgrade" in source


def test_graph_source_pointer_migration_pins_exact_analysis_runs() -> None:
    source = Path("migrations/versions/20260831_0023_graph_source_pointer_runs.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260828_0022"' in source
    assert CURRENT_MIGRATION_REVISION == "20260903_0027"
    assert "analysis_run_id" in source
    assert "fk_knowledge_node_source_analysis" in source
    assert "fk_knowledge_edge_source_analysis" in source
    assert "without one exact accepted Analysis Run" in source
    assert "prevents safe downgrade" in source
    assert "DELETE FROM" not in source


def test_knowledge_analysis_rbac_migration_is_additive_and_exact() -> None:
    source = Path("migrations/versions/20260824_0012_knowledge_analysis_rbac.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | Sequence[str] | None = "20260823_0011"' in source
    assert "ALTER TABLE" not in source
    assert "DROP TABLE" not in source
    assert '_stable_id("role_", "ADMIN")' in source
    for permission in (
        "knowledge_analysis:read",
        "knowledge_analysis:create",
        "knowledge_analysis:review",
    ):
        assert permission in source


def test_education_graph_migration_is_additive_indexed_and_pointer_oriented() -> None:
    source = Path(
        "migrations/versions/20260824_0013_add_immutable_education_graph_snapshots.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "20260824_0012"' in source
    assert "UPDATE item_revisions" not in source
    assert "DELETE FROM" not in source
    for table_name in (
        "knowledge_corpora",
        "knowledge_corpus_revisions",
        "knowledge_graph_snapshots",
        "knowledge_nodes",
        "knowledge_edges",
        "knowledge_node_source_pointers",
        "knowledge_edge_source_pointers",
        "curriculum_unit_closure",
        "item_element_refs",
    ):
        assert f'"{table_name}"' in source
    for index_name in (
        "ix_knowledge_edge_outbound",
        "ix_knowledge_edge_inbound",
        "ix_curriculum_closure_descendants",
        "ix_curriculum_closure_ancestors",
        "ix_item_element_revision_kind",
        "ix_item_element_reverse",
    ):
        assert index_name in source

    graph_tables = {name for name in Base.metadata.tables if name.startswith("knowledge_")}
    assert "knowledge_graph_snapshots" in graph_tables
    for table_name in graph_tables | {"curriculum_unit_closure", "item_element_refs"}:
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
    snapshot = Base.metadata.tables["knowledge_graph_snapshots"]
    assert not snapshot.c.snapshot_sha256.unique


def test_existing_hwpx_partial_index_remains_in_composed_metadata() -> None:
    table = Base.metadata.tables["hwpx_application_builds"]
    indexes = {str(index.name): index for index in table.indexes if index.name is not None}
    requested = indexes["ix_hwpx_application_builds_requested_fifo"]
    assert not requested.unique
    assert str(requested.dialect_options["postgresql"]["where"]) == "state = 'REQUESTED'"


def test_evidence_retrieval_migration_is_additive_indexed_and_pointer_oriented() -> None:
    source = Path("migrations/versions/20260824_0014_evidence_bundle_retrieval.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | Sequence[str] | None = "20260824_0013"' in source
    assert "UPDATE item_revisions" not in source
    assert "DELETE FROM evidence_" not in source
    for table_name in (
        "knowledge_node_terms",
        "education_retrieval_access_policy_revisions",
        "education_retrieval_requests",
        "evidence_bundles",
        "evidence_bundle_revisions",
        "evidence_bundle_entries",
    ):
        assert f'"{table_name}"' in source
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
    for index_name in (
        "ix_knowledge_node_term_lookup",
        "ix_education_retrieval_snapshot_created",
        "ix_evidence_bundle_entry_nodes",
        "ix_evidence_bundle_entry_anchors",
    ):
        assert index_name in source
    assert "accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9" in source
    assert "sha256:bf35bc53cd756efdff81fe4154a639968083b5d91932bdc09deaa439b32fcbc0" in source
    request_table = Base.metadata.tables["education_retrieval_requests"]
    assert request_table.c.idempotency_key.unique
    entries = Base.metadata.tables["evidence_bundle_entries"]
    assert not {"payload", "bytes", "content", "markdown", "nas_path"}.intersection(
        entries.columns.keys()
    )


def test_legacy_usage_migration_is_additive_indexed_and_review_gated() -> None:
    source = Path("migrations/versions/20260824_0015_legacy_product_usage_intake.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | Sequence[str] | None = "20260824_0014"' in source
    assert "UPDATE items" not in source
    assert "UPDATE usage_records" not in source
    assert "DELETE FROM" not in source
    for table_name in (
        "assessment_forms",
        "assessment_form_revisions",
        "assessment_assemblies",
        "assessment_assembly_revisions",
        "assessment_item_placements",
        "publications",
        "publication_revisions",
        "usage_records_v1",
        "legacy_usage_mapping_contract_revisions",
        "legacy_usage_imports",
        "legacy_usage_row_proposals",
        "legacy_usage_row_reviews",
        "product_usage_projections",
    ):
        assert f'"{table_name}"' in source
        assert table_name in Base.metadata.tables
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
    for index_name in (
        "ix_usage_v1_item_reverse",
        "ix_usage_v1_product_revision",
        "ix_usage_v1_form_revision",
        "ix_usage_v1_publication",
        "ix_usage_v1_import",
        "ix_legacy_usage_rows_import_state",
        "ix_legacy_usage_rows_import_source_key",
    ):
        assert index_name in source
    assert "legacy_usage_imports_transition" in source
    assert "enforce_legacy_usage_import_transition" in source
    assert "legacy usage import immutable fields cannot be changed" in source
    assert "OLD.state = 'PROPOSED' AND NEW.state IN ('REVIEWED','FAILED')" in source
    assert "OLD.state = 'REVIEWED' AND NEW.state IN ('COMMITTED','FAILED')" in source
    immutable_trigger_block = source[
        source.index("    for table in (") : source.index("\n\n\ndef downgrade")
    ]
    assert '"legacy_usage_row_proposals",' in immutable_trigger_block
    assert '"legacy_usage_row_reviews",' in immutable_trigger_block
    assert 'f"CREATE TRIGGER {table}_immutable' in immutable_trigger_block
    usage = Base.metadata.tables["usage_records_v1"]
    assert {"legacy_usage_import_id", "legacy_usage_row_id"}.issubset(usage.columns.keys())
    assert not {"bytes", "payload", "workbook", "nas_path"}.intersection(usage.columns.keys())


def test_educational_document_migration_is_pointer_only_and_revision_immutable() -> None:
    source = Path("migrations/versions/20260825_0016_educational_documents.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260824_0015"' in source
    for table_name in (
        "educational_documents",
        "educational_document_revisions",
        "educational_document_registrations",
    ):
        assert f'"{table_name}"' in source
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
        assert not {"bytes", "payload", "pdf", "markdown", "nas_path"}.intersection(
            table.columns.keys()
        )
    for index_name in (
        "ix_educational_document_revision_publisher_volume",
        "ix_educational_document_revision_source_sha",
        "ix_educational_document_registrations_state",
    ):
        assert index_name in source
    assert "BEFORE UPDATE OR DELETE ON educational_document_revisions" in source
    assert "educational document revisions are immutable" in source
    revisions = Base.metadata.tables["educational_document_revisions"]
    assert {"source_artifact_id", "source_artifact_revision_id", "source_sha256"}.issubset(
        revisions.columns.keys()
    )


def test_document_analysis_source_migration_is_additive_pointer_only_and_indexed() -> None:
    source = Path(
        "migrations/versions/20260825_0017_knowledge_analysis_document_sources.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260825_0016"' in source
    assert "DOCUMENT_REVISION" in source
    for table_name in (
        "knowledge_analysis_runs",
        "knowledge_snapshot_analyses",
        "evidence_bundle_entries",
    ):
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
        assert not {"payload", "pdf", "markdown", "nas_path"}.intersection(table.columns.keys())
    for table_name in ("knowledge_analysis_runs", "evidence_bundle_entries"):
        assert {
            "educational_document_id",
            "educational_document_revision_id",
        }.issubset(Base.metadata.tables[table_name].columns.keys())
    assert "ix_knowledge_analysis_document_revision" in source
    assert "ix_evidence_bundle_entry_document_revision" in source
    assert "ck_knowledge_analysis_source_pointer_family" in source
    assert "ck_evidence_bundle_entry_source_family" in source
    assert "uq_educational_document_revision_identity" in source
    for constraint_name in (
        "fk_knowledge_analysis_educational_document_revision_identity",
        "fk_evidence_entry_educational_document_revision_identity",
    ):
        assert constraint_name in source
    assert "fk_knowledge_analysis_educational_document_revision_identity" in {
        constraint.name
        for constraint in Base.metadata.tables["knowledge_analysis_runs"].foreign_key_constraints
    }
    assert "fk_evidence_entry_educational_document_revision_identity" in {
        constraint.name
        for constraint in Base.metadata.tables["evidence_bundle_entries"].foreign_key_constraints
    }


def test_knowledge_analysis_batch_migration_is_pointer_only_and_indexed() -> None:
    source = Path("migrations/versions/20260826_0018_knowledge_analysis_batches.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260825_0017"' in source
    for table_name in (
        "knowledge_analysis_batches",
        "knowledge_analysis_batch_ranges",
        "knowledge_analysis_batch_events",
    ):
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
        assert not {"pdf", "markdown", "token", "session_id", "password"}.intersection(
            table.columns.keys()
        )
    assert "uq_knowledge_analysis_batch_active_range" in source
    assert "ix_knowledge_analysis_batch_range_claim" in source
    assert "ix_knowledge_analysis_batch_range_document_pages" in source
    assert "ck_knowledge_analysis_batch_range_pointer_contract" in source
    assert "FOR UPDATE" not in source


def test_workflow_command_claim_index_includes_delayed_availability() -> None:
    table = Base.metadata.tables["workflow_commands"]
    indexes = {str(index.name): index for index in table.indexes if index.name is not None}
    claimable = indexes["ix_workflow_commands_claimable"]
    assert tuple(column.name for column in claimable.columns) == (
        "state",
        "available_at",
        "created_at",
        "command_id",
    )
