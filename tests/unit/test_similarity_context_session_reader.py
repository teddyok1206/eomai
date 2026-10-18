"""Same-root composition using synthetic current owners, never production IAM or a model."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_context_service import SimilarityContextApplicationService
from eom_workflow_runner.similarity_context_session_reader import (
    CatalogSimilaritySessionContextReader,
)

from tests.unit.test_similarity_context_service import CALLER, case


def session_case():
    request, sources, numeric = case()
    expected = SimilarityContextApplicationService(sources, numeric).compose(CALLER, request)
    calls = []
    roots = []
    readers = []
    hooks = []
    read_sets = []
    population_read_set = object()
    root = SimpleNamespace(is_active=True)
    session = SimpleNamespace(get_transaction=lambda: root, in_nested_transaction=lambda: False)

    def prepare(
        actual_session, caller, actual_request, *, artifact_reader=None, population_read_set=None
    ):
        if artifact_reader is not None:
            artifact_reader.require_session(actual_session)
            readers.append(artifact_reader)
        if population_read_set is not None:
            read_sets.append(population_read_set)
        assert caller == CALLER and actual_request == request
        roots.append(actual_session)
        calls.append("prepare")
        if hooks:
            hooks.pop(0)()
        return sources.prepared

    def read(
        actual_session,
        caller,
        actual_request,
        prepared,
        *,
        artifact_reader=None,
        population_read_set=None,
    ):
        if artifact_reader is not None:
            artifact_reader.require_session(actual_session)
            readers.append(artifact_reader)
        if population_read_set is not None:
            read_sets.append(population_read_set)
        assert caller == CALLER and actual_request == request and prepared == sources.prepared
        roots.append(actual_session)
        calls.append("read")
        return sources.reads

    catalog = SimpleNamespace(
        create_similarity_population_read_set_in_session=Mock(return_value=population_read_set),
        prepare_similarity_context_in_session=prepare,
        read_similarity_views_in_session=read,
        prepare_similarity_context=Mock(side_effect=AssertionError("new root")),
        read_similarity_views=Mock(side_effect=AssertionError("new root")),
    )

    def query_read(actual_session, caller, actual_request, prepared):
        assert caller == CALLER and actual_request == request and prepared == sources.prepared
        roots.append(actual_session)
        calls.append("query")
        return numeric.value

    query = SimpleNamespace(
        owner=SimpleNamespace(catalog=catalog),
        artifact_reader=None,
        resolve_reference_query_in_session=query_read,
        resolve_reference_query=Mock(side_effect=AssertionError("new root")),
    )
    return SimpleNamespace(
        request=request,
        sources=sources,
        expected=expected,
        calls=calls,
        roots=roots,
        readers=readers,
        read_sets=read_sets,
        population_read_set=population_read_set,
        hooks=hooks,
        session=session,
        query=query,
        catalog=catalog,
        reader=CatalogSimilaritySessionContextReader(query),
    )


def test_pure_common_composition_retains_one_root_and_identical_ranking():
    value = session_case()
    result = value.reader.compose_in_session(value.session, CALLER, value.request)
    assert result == value.expected
    assert value.calls == ["prepare", "query", "read", "prepare"]
    assert value.roots == [value.session] * 4
    value.catalog.prepare_similarity_context.assert_not_called()
    value.catalog.read_similarity_views.assert_not_called()
    value.query.resolve_reference_query.assert_not_called()


def test_common_source_ports_forward_the_same_root_local_reader_to_every_fresh_phase():
    value = session_case()
    reader = PinnedArtifactReadContext(value.session, CatalogSettings())
    value.query.artifact_reader = reader
    result = value.reader.compose_in_session(value.session, CALLER, value.request)
    assert result == value.expected
    assert value.readers == [reader, reader, reader]
    assert value.read_sets == [value.population_read_set] * 3
    value.catalog.create_similarity_population_read_set_in_session.assert_called_once_with(
        value.session, CALLER, value.request, artifact_reader=reader
    )
    assert value.calls == ["prepare", "query", "read", "prepare"]


def test_same_root_does_not_replace_the_full_late_source_reauthorization():
    value = session_case()
    value.hooks.extend(
        (
            lambda: None,
            lambda: setattr(
                value.sources, "prepared", replace(value.sources.prepared, truncated=True)
            ),
        )
    )
    result = value.reader.compose_in_session(value.session, CALLER, value.request)
    assert result.status == "FAILED" and result.error_code == "SOURCE_REVOKED"
    assert not result.candidates and result.population is None
    assert value.roots == [value.session] * 4


def test_initial_current_source_denial_prevents_query_or_vector_read():
    value = session_case()

    def deny():
        raise SimilarityContextReadError("SOURCE_ACCESS_DENIED")

    value.hooks.append(deny)
    result = value.reader.compose_in_session(value.session, CALLER, value.request)
    assert result.status == "FAILED" and result.error_code == "SOURCE_ACCESS_DENIED"
    assert value.calls == ["prepare"]


@pytest.mark.parametrize("fault", ("missing", "inactive", "nested"))
def test_missing_or_nested_roots_fail_before_source_query_or_member_work(fault):
    value = session_case()
    if fault == "missing":
        value.session.get_transaction = lambda: None
    elif fault == "inactive":
        value.session.get_transaction = lambda: SimpleNamespace(is_active=False)
    else:
        value.session.in_nested_transaction = lambda: True
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        value.reader.compose_in_session(value.session, CALLER, value.request)
    assert value.calls == []
