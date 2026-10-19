"""Repository metadata/SQL projections only; no real source authorization or DB."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryError,
    RegisteredReviewEmbeddingBindingLookupKey,
    embedding_binding_lookup_sort_key,
)
from eom_catalog_service.embedding_registry_repository import (
    ASSOCIATION_COLUMNS,
    REGISTERED_REVIEW_ASSOCIATION_COLUMNS,
    EmbeddingRegistryRepository,
    binding_columns,
)
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.orm import Session

from tests.unit.mixed_embedding_fixtures import mixed_embedding_case


def _keys():
    *_prefix, index = mixed_embedding_case()
    columns = [binding_columns(value) for value in index.bindings]
    legacy = next(row for row in columns if row["evidence_kind"] == "ACCEPTED_SOLUTION_ANALYSIS")
    registered = next(
        row for row in columns if row["evidence_kind"] == "REGISTERED_ITEM_REVIEW_SOLUTION"
    )
    return (
        EmbeddingBindingLookupKey(*(legacy[name] for name in ASSOCIATION_COLUMNS)),
        RegisteredReviewEmbeddingBindingLookupKey(
            *(registered[name] for name in REGISTERED_REVIEW_ASSOCIATION_COLUMNS)
        ),
    )


def test_scalar_binding_mapping_keeps_real_base_and_separate_review_not_fake_solution():
    *_prefix, index = mixed_embedding_case()
    for value in index.bindings:
        row = binding_columns(value)
        if value.schema_version.endswith("/1.0"):
            assert row["evidence_kind"] == "ACCEPTED_SOLUTION_ANALYSIS"
            assert row["review_job_id"] is None and row["review_evidence_sha256"] is None
            assert row["base_analysis_run_id"] == value.solution_evidence.base_analysis_run_id
            assert (
                row["solution_analysis_run_id"] == value.solution_evidence.solution_analysis_run_id
            )
        else:
            assert row["evidence_kind"] == "REGISTERED_ITEM_REVIEW_SOLUTION"
            assert row["base_analysis_run_id"] == value.base_analysis_run_id
            assert (
                row["solution_analysis_run_id"] is None and row["solution_pointer_sha256"] is None
            )
            assert row["review_job_id"] == value.review_evidence.review.job_id
            assert row["review_evidence_sha256"] == value.review_evidence.evidence_sha256


def test_key_families_keep_legacy_ten_positionals_and_have_explicit_stable_order():
    legacy, registered = _keys()
    assert len(legacy.columns()) == 10 and len(registered.columns()) == 11
    assert None not in registered.columns()
    assert sorted((registered, legacy), key=embedding_binding_lookup_sort_key) == [
        legacy,
        registered,
    ]
    assert embedding_binding_lookup_sort_key(registered)[0] == "REGISTERED_ITEM_REVIEW_SOLUTION"


def test_mixed_batch_lookup_uses_two_indexed_nonnullable_branches_not_null_tuple_comparison():
    legacy, registered = _keys()
    session = Mock(spec=Session)
    session.scalars.side_effect = [
        (SimpleNamespace(binding_sha256="old"),),
        (SimpleNamespace(binding_sha256="new"),),
    ]
    result = EmbeddingRegistryRepository(session).bindings((registered, legacy))
    assert set(result) == {"old", "new"} and session.scalars.call_count == 2
    for call, expected in zip(
        session.scalars.call_args_list,
        (ASSOCIATION_COLUMNS, REGISTERED_REVIEW_ASSOCIATION_COLUMNS),
        strict=True,
    ):
        statement = call.args[0]
        sql = str(statement.compile(dialect=dialect()))
        assert " IN (" in sql and "evidence_kind =" in sql
        assert statement.get_execution_options()["populate_existing"] is True
        assert all(name in sql for name in expected)
        values = next(
            value for value in statement.compile().params.values() if isinstance(value, list)
        )
        assert all(None not in row for row in values)


def test_mixed_missing_antijoins_preserve_input_order_with_at_most_one_query_per_family():
    legacy, registered = _keys()
    session = Mock(spec=Session)
    session.execute.side_effect = [
        Mock(all=Mock(return_value=[legacy.columns()])),
        Mock(all=Mock(return_value=[registered.columns()])),
    ]
    result = EmbeddingRegistryRepository(session).missing_bindings((registered, legacy))
    assert result == (registered, legacy) and session.execute.call_count == 2
    for call in session.execute.call_args_list:
        sql = str(call.args[0].compile(dialect=dialect()))
        assert "VALUES" in sql and "NOT (EXISTS" in sql and "evidence_kind =" in sql
        assert all(value is not None for value in call.args[0].compile().params.values())


@pytest.mark.parametrize("fault", ("null_review", "too_many", "unknown"))
def test_bad_key_selection_is_rejected_before_any_query(fault):
    _legacy, registered = _keys()
    if fault == "null_review":
        keys = (replace(registered, review_job_id=None),)
    elif fault == "too_many":
        keys = (registered,) * 1025
    else:
        keys = (object(),)
    session = Mock(spec=Session)
    with pytest.raises(EmbeddingRegistryError):
        EmbeddingRegistryRepository(session).bindings(keys)
    session.scalars.assert_not_called()
    if fault == "null_review":
        with pytest.raises(EmbeddingRegistryError):
            embedding_binding_lookup_sort_key(keys[0])
