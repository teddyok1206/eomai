"""Pagination orchestration with explicit synthetic admission; no source authority."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import public_solution_source_capture as module
from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_source_capture import CatalogPublicSolutionSourceCapture

from tests.unit.test_public_solution_encoding import public_entry, public_recipe


def case(monkeypatch, count=1100):
    example = public_entry()
    command = InferenceTransferCorpusReadCommand(
        "operator_" + "1" * 32,
        example.graph_snapshot,
        example.policy_revision_id,
        example.policy_sha256,
        ("APPROVED_ITEM", "PAST_EXAM"),
        1024,
        InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS,
    )
    owner = object.__new__(CatalogPublicSolutionSourceCapture)
    owner.sources = Mock()
    scope = NS(maximum_candidates=1024)
    owner.sources.authorize_scope_in_session.return_value = scope
    session, fence, reader = Mock(), Mock(), Mock()
    all_members = tuple(
        ("itemrev_" + f"{i:032x}", "analysisrun_" + f"{i:032x}") for i in range(count)
    )
    statements = []

    def statement(_scope, *, after_source_revision_id):
        assert _scope is scope
        statements.append(after_source_revision_id)
        return after_source_revision_id

    def execute(after):
        return tuple(value for value in all_members if after is None or value[0] > after)[:1025]

    selections = []

    def capture(_session, selected, _recipe, **kwargs):
        assert _session is session and kwargs["identity_fence"] is fence
        keys = selected.source_revision_ids
        selections.append(keys)
        sources = tuple(
            AdmittedInferenceTransferSource(
                run, example.source.model_copy(update={"item_revision_id": key})
            )
            for key, run in all_members
            if key in set(keys)
        )
        return CapturedPublicSolutionSources(
            (),
            keys,
            keys,
            scope,
            AdmittedInferenceTransferCorpus((), (), False, len(keys), sources),
        )

    session.execute.side_effect = execute
    monkeypatch.setattr(module, "candidate_source_page_statement", statement)
    monkeypatch.setattr(module, "PinnedArtifactReadContext", Mock())
    monkeypatch.setattr(owner, "capture_in_session", capture)
    return NS(**locals())


def run(value, maximum=16384):
    return value.owner.capture_population_in_session(
        value.session,
        value.command,
        public_recipe(),
        identity_fence=value.fence,
        artifact_reader=value.reader,
        maximum_population_sources=maximum,
    )


def test_population_larger_than_1024_uses_bounded_pages_and_rechecks_exact_membership(monkeypatch):
    value = case(monkeypatch)
    result = run(value)
    assert tuple(map(len, value.selections)) == (1024, 76)
    assert result.source_revision_ids == tuple(key for key, _ in value.all_members)
    assert result.corpus.missing_solution_reports == 1100 and not result.corpus.truncated
    assert value.statements == [None, value.all_members[1023][0]] * 2
    assert value.owner.sources.authorize_scope_in_session.call_count == 2
    value.reader.revalidate_provenance.assert_called_once()


def test_empty_population_still_checks_authority_twice(monkeypatch):
    value = case(monkeypatch, count=0)
    assert run(value).source_revision_ids == ()
    assert value.selections == []
    assert value.owner.sources.authorize_scope_in_session.call_count == 2


def test_maximum_is_not_silent_truncation(monkeypatch):
    value = case(monkeypatch)
    with pytest.raises(ValueError, match="POPULATION_BOUND_EXCEEDED"):
        run(value, maximum=1024)


def test_page_edge_or_final_membership_change_is_rejected(monkeypatch):
    value = case(monkeypatch)
    execute = value.session.execute.side_effect
    calls = 0

    def changed(after):
        nonlocal calls
        calls += 1
        rows = execute(after)
        return rows[:-1] if calls >= 3 else rows

    value.session.execute.side_effect = changed
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        run(value)


def test_full_population_capture_never_accepts_a_selected_subset_as_complete(monkeypatch):
    value = case(monkeypatch)
    value.command = replace(value.command, source_revision_ids=(value.all_members[0][0],))
    with pytest.raises(ValueError, match="POPULATION_BOUND_INVALID"):
        run(value)
