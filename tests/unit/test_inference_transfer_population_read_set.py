"""Primitive observation guards/counts; actual SQL semantics have disposable PG tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_service import inference_transfer_population_read_set as module
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_identifiers import canonical_json_bytes
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from tests.unit.test_inference_transfer_candidate_admission import admission_scope

TABLE_GROUPS = (
    ("knowledge_graph_snapshots", "graph_snapshot"),
    ("knowledge_snapshot_analyses", "membership"),
    ("item_revisions", "item_revisions"),
    ("items", "items"),
    ("item_components", "components"),
    ("knowledge_node_source_pointers", "graph_pointers"),
    ("knowledge_analysis_runs", "base_and_solution_runs"),
    ("legacy_item_extraction_acceptances", "extraction_acceptances"),
    ("legacy_item_extraction_decisions", "extraction_decisions"),
    ("legacy_item_extraction_batch_work_units", "extraction_units"),
    ("legacy_item_extraction_batches", "extraction_batches"),
    ("assessment_source_bundle_revisions", "source_bundles"),
    ("assessment_layout_observations", "layouts"),
    ("artifacts", "artifacts"),
    ("artifact_revisions", "artifact_revisions"),
    ("jobs", "producer_jobs"),
)


class PrimitiveResult:
    def __init__(self, rows):
        self.rows = rows
        self.batch_size = None
        self.closed = False

    def yield_per(self, size):
        self.batch_size = size
        return self

    def mappings(self):
        yield from self.rows

    def close(self):
        self.closed = True


class PrimitiveSession:
    """Only SQL-shaped primitive rows; an ORM lookup would fail the test."""

    def __init__(self):
        self.root = SimpleNamespace(is_active=True)
        self.nested = False
        self.new, self.dirty, self.deleted = set(), set(), set()
        values = {
            "analysis_run_id": "analysisrun_fixture",
            "source_revision_id": "itemrev_fixture",
            "item_id": "item_fixture",
            "observed_source_kind": "PAST_EXAM",
            "observed_acceptance_id": "acceptance_fixture",
            "observed_result_id": "result_fixture",
            "observed_proposal_id": "proposal_fixture",
            "observed_item_number": 1,
            "artifact_id": "artifact_fixture",
            "artifact_revision_id": "rev_fixture",
            "source_artifact_id": "artifact_graph_source",
            "source_artifact_revision_id": "rev_graph_source",
            "accepted_result_artifact_id": "artifact_accepted",
            "accepted_result_artifact_revision_id": "rev_accepted",
            "proposal_artifact_id": "artifact_proposal",
            "proposal_artifact_revision_id": "rev_proposal",
            "result_artifact_id": "artifact_result",
            "result_artifact_revision_id": "rev_result",
            "acceptance_artifact_id": "artifact_acceptance",
            "acceptance_artifact_revision_id": "rev_acceptance",
            "extraction_batch_id": "batch_fixture",
            "assessment_source_bundle_revision_id": "bundle_fixture",
            "manifest_artifact_id": "artifact_batch",
            "manifest_artifact_revision_id": "rev_batch",
            "job_id": "job_fixture",
        }
        self.rows = {table: [deepcopy(values)] for table, _group in TABLE_GROUPS}
        self.statements = []
        self.results = []
        self.digest_override = None

    def get_transaction(self):
        return self.root

    def in_nested_transaction(self):
        return self.nested

    def execute(self, statement, *, execution_options):
        self.statements.append((statement, execution_options))
        selected = statement.get_final_froms()[0].element
        table = next(iter(selected.selected_columns)).table.name
        keys = tuple(
            column.key for column in statement.selected_columns if column.key != "_row_sha256"
        )
        result = PrimitiveResult(
            [
                {
                    **{key: row[key] for key in keys},
                    "_row_sha256": self.digest_override
                    if self.digest_override is not None
                    else sha256(canonical_json_bytes(row)).digest(),
                }
                for row in self.rows[table]
            ]
        )
        self.results.append(result)
        return result

    def get(self, *_args, **_kwargs):
        pytest.fail("population observations must not inherit ORM identity-map values")


def observe(session, *, maximum=1024):
    return module.observe_inference_transfer_population(
        cast(Session, session),
        admission_scope(maximum=maximum),
        artifact_identities=(),
        layout_observation_ids=("layout_fixture",),
    )


def test_fixed_named_groups_are_frozen_and_use_narrow_streaming_core_queries():
    session = PrimitiveSession()
    result = observe(session)
    assert tuple(group.group for group in result.groups) == tuple(
        group for _, group in TABLE_GROUPS
    )
    assert all(group.row_count == 1 for group in result.groups)
    assert all(
        group.sha256.startswith("sha256:") and len(group.sha256) == 71 for group in result.groups
    )
    with pytest.raises(FrozenInstanceError):
        result.groups = ()
    with pytest.raises(FrozenInstanceError):
        result.groups[0].row_count = 0
    assert len(session.statements) == 16
    for statement, options in session.statements:
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "sha256(convert_to(CAST(row_to_json(" in sql
        assert "ORDER BY" in sql and "LIMIT" in sql
        assert options == {"stream_results": True, "max_row_buffer": 128}
        assert all(
            description.get("entity") is None for description in statement.column_descriptions
        )
        assert not {"manifest", "result", "canonical_request", "metadata_json"}.intersection(
            column.key for column in statement.selected_columns
        )
    assert all(result.closed and result.batch_size == 128 for result in session.results)


@pytest.mark.parametrize("table,group", TABLE_GROUPS)
def test_every_explicit_dependency_digest_changes_the_corresponding_observation(table, group):
    session = PrimitiveSession()
    before = observe(session)
    session.rows[table][0]["current_primitive_witness"] = "changed"
    after = observe(session)
    assert tuple(
        current.group
        for previous, current in zip(before.groups, after.groups, strict=True)
        if previous != current
    ) == (group,)


@pytest.mark.parametrize("count", (1, 545))
def test_source_scale_keeps_sixteen_batches_and_all_unranked_pointer_rows(count):
    session = PrimitiveSession()
    for table, _group in TABLE_GROUPS:
        if table == "knowledge_graph_snapshots":
            continue
        session.rows[table] = [
            session.rows[table][0] | {"synthetic_ordinal": index} for index in range(count)
        ]
    if count == 545:
        template = session.rows["knowledge_node_source_pointers"][0]
        session.rows["knowledge_node_source_pointers"] = [
            template | {"synthetic_pointer": index} for index in range(73345)
        ]
    first = observe(session)
    assert len(session.statements) == 16
    assert observe(session) == first and len(session.statements) == 32
    groups = {group.group: group for group in first.groups}
    assert groups["membership"].row_count == count
    assert groups["graph_pointers"].row_count == (73345 if count == 545 else count)


@pytest.mark.parametrize(
    "fault", ("missing_root", "closed_root", "nested", "new", "dirty", "deleted")
)
def test_root_or_pending_mutation_errors_fail_before_observing_any_rows(fault):
    session = PrimitiveSession()
    if fault == "missing_root":
        session.root = None
    elif fault == "closed_root":
        session.root.is_active = False
    elif fault == "nested":
        session.nested = True
    else:
        getattr(session, fault).add(object())
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        observe(session)
    assert not session.statements


@pytest.mark.parametrize("digest", (b"short", "not-binary", 1))
def test_invalid_server_digest_fails_closed_and_closes_stream(digest):
    session = PrimitiveSession()
    session.digest_override = digest
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        observe(session)
    assert len(session.results) == 1 and session.results[0].closed


def test_member_bound_preserves_overflow_instead_of_truncating_the_population():
    session = PrimitiveSession()
    session.rows["knowledge_snapshot_analyses"] *= 2
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        observe(session, maximum=1)
    assert len(session.results) == 2 and all(result.closed for result in session.results)


def test_current_scope_predicates_are_the_official_prelimit_selection():
    session = PrimitiveSession()
    scope = replace(admission_scope(), source_revision_ids=("itemrev_" + "1" * 32,))
    module.observe_inference_transfer_population(
        cast(Session, session), scope, artifact_identities=()
    )
    statement = session.statements[1][0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "eligible_snapshot_analyses AS MATERIALIZED" in sql
    assert "knowledge_node_source_pointers" in sql and "knowledge_nodes" in sql
    assert "knowledge_snapshot_analyses.source_revision_id IN" in sql
    assert "knowledge_analysis_runs.state" in sql and "items.lifecycle_state" in sql
