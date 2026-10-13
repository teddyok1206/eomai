"""Pure seed/delta metadata composition; no worker, model, Artifact or IAM claims."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingVectorRowRef,
    embedding_input_set_sha256,
    validate_embedding_source_bindings,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_assembly import assemble_embedding_index_revision
from eom_workflow.local_embedding_source_plan import parse_local_embedding_source_plan

from tests.unit.inference_transfer_embedding_fixtures import (
    index_pointer,
    seal,
    shard_pointer,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import native_fixture


def rows_for(native, seed="a"):
    shard = vector_shard(
        tuple(row.encoding for row in native.native_input.rows), space=native.plan.space
    )
    pointer = shard_pointer(shard, seed)
    rows = tuple(
        RegisteredEmbeddingRow(
            encoding,
            EmbeddingVectorRowRef(
                shard_manifest=pointer, row_index=ordinal, encoding_sha256=encoding.encoding_sha256
            ),
        )
        for ordinal, encoding in enumerate(shard.rows)
    )
    return rows, (pointer, shard)


def assemble(plan, rows, shards, *, previous=None, revision="2"):
    return assemble_embedding_index_revision(
        plan,
        available_rows=rows,
        shards=shards,
        index_id="embeddingindex_" + "1" * 32,
        index_revision_id="embeddingindexrev_" + revision * 32,
        previous=previous,
        created_at=NOW,
    )


def test_seed_is_deterministic_and_keeps_exact_profile_report_and_numeric_rows() -> None:
    native = native_fixture()
    rows, shard = rows_for(native)
    first = assemble(native.plan, rows, (shard,))
    assert assemble(native.plan, tuple(reversed(rows)), (shard,)) == first
    assert len(first.index.bindings) == 2
    validate_embedding_source_bindings(first.index.bindings, native.entries, first.shards)
    assert {b.encoding for b in first.index.bindings} == {r.encoding for r in rows}


def test_delta_keeps_previous_rows_and_pins_exact_predecessor() -> None:
    a, b, full = native_fixture("a"), native_fixture("b"), native_fixture()
    old_rows, old_shard = rows_for(a, "a")
    new_rows, new_shard = rows_for(b, "b")
    first = assemble(a.plan, old_rows, (old_shard,))
    previous = index_pointer(first.index), first.index
    delta = assemble(
        full.plan, (*new_rows, *old_rows), (new_shard, old_shard), previous=previous, revision="3"
    )
    assert len(delta.index.bindings) == 2 and len(delta.index.shards) == 2
    assert delta.index.bindings[0] == first.index.bindings[0]
    assert delta.index.previous_manifest == previous[0]
    validate_embedding_source_bindings(delta.index.bindings, full.entries, delta.shards)


def test_graph_revision_rebuilds_bindings_without_reencoding() -> None:
    native = native_fixture()
    rows, shard = rows_for(native)
    old = assemble(native.plan, rows, (shard,))
    body = native.plan.model_dump(mode="json")
    body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    plan = parse_local_embedding_source_plan(seal(body, "plan_sha256"))
    new = assemble(
        plan, rows, (shard,), previous=(index_pointer(old.index), old.index), revision="3"
    )
    for before, after in zip(old.index.bindings, new.index.bindings, strict=True):
        assert before.encoding == after.encoding and before.row_ref == after.row_ref
        assert before.binding_sha256 != after.binding_sha256
        assert after.graph_snapshot == plan.graph_snapshot


def test_revoked_source_is_not_copied_from_previous_index() -> None:
    full, allowed = native_fixture(), native_fixture("a")
    rows, shard = rows_for(full)
    previous_index = assemble(full.plan, rows, (shard,)).index
    key = allowed.plan.demands[0].encoding.encoding_sha256
    selected = tuple(row for row in rows if row.encoding.encoding_sha256 == key)
    result = assemble(
        allowed.plan,
        selected,
        (shard,),
        previous=(index_pointer(previous_index), previous_index),
        revision="3",
    )
    assert tuple(b.source.item_revision_id for b in result.index.bindings) == (
        allowed.plan.sources[0].item_revision_id,
    )
    with pytest.raises(ValueError, match="ROW_INVALID"):
        assemble(allowed.plan, rows, (shard,))


def test_missing_report_has_real_partial_coverage_not_a_placeholder() -> None:
    native = native_fixture()
    body = native.plan.model_dump(mode="json")
    body["demands"] = body["demands"][:1]
    body["missing_solution_report_revision_ids"] = [native.plan.sources[1].item_revision_id]
    body["encoding_set_sha256"] = embedding_input_set_sha256((native.plan.demands[0].encoding,))
    plan = parse_local_embedding_source_plan(seal(body, "plan_sha256"))
    rows, shard = rows_for(native_fixture("a"))
    result = assemble(plan, rows, (shard,))
    assert len(plan.sources) == 2 and len(result.index.bindings) == 1
    assert plan.missing_solution_report_revision_ids == (native.plan.sources[1].item_revision_id,)


@pytest.mark.parametrize(
    "fault",
    ["duplicate_row", "foreign_row", "wrong_row", "missing_shard", "duplicate_shard", "hash"],
)
def test_corrupt_duplicate_or_foreign_values_are_explicit_failures(fault: str) -> None:
    native = native_fixture()
    rows, shard = rows_for(native)
    shards = (shard,)
    if fault == "duplicate_row":
        rows = (*rows, rows[0])
    if fault == "foreign_row":
        rows = rows_for(native_fixture("c"))[0]
    if fault == "wrong_row":
        row = rows[0]
        rows = (replace(row, row_ref=row.row_ref.model_copy(update={"row_index": 1000})), *rows[1:])
    if fault == "missing_shard":
        shards = ()
    if fault == "duplicate_shard":
        shards = (shard, shard)
    if fault == "hash":
        shards = ((shard[0].model_copy(update={"sha256": "sha256:" + "0" * 64}), shard[1]),)
    with pytest.raises(ValueError):
        assemble(native.plan, rows, shards)


def test_empty_numeric_coverage_never_creates_an_empty_success_index() -> None:
    with pytest.raises(ValueError, match="NO_AVAILABLE_BINDING"):
        assemble(native_fixture().plan, (), ())
