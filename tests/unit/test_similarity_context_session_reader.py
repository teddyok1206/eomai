"""Same-root composition using synthetic current owners, never production IAM or a model."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
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
    hooks = []
    root = SimpleNamespace(is_active=True)
    session = SimpleNamespace(get_transaction=lambda: root, in_nested_transaction=lambda: False)

    def prepare(actual_session, caller, actual_request):
        assert caller == CALLER and actual_request == request
        roots.append(actual_session)
        calls.append("prepare")
        if hooks:
            hooks.pop(0)()
        return sources.prepared

    def read(actual_session, caller, actual_request, prepared):
        assert caller == CALLER and actual_request == request and prepared == sources.prepared
        roots.append(actual_session)
        calls.append("read")
        return sources.reads

    catalog = SimpleNamespace(
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
        resolve_reference_query_in_session=query_read,
        resolve_reference_query=Mock(side_effect=AssertionError("new root")),
    )
    return SimpleNamespace(
        request=request,
        sources=sources,
        expected=expected,
        calls=calls,
        roots=roots,
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
