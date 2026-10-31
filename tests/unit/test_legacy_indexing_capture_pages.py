"""Synthetic admission leaves: retain legacy population semantics with bounded readers."""

from dataclasses import dataclass
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import inference_transfer_snapshot_catalog_adapter as module
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import EmbeddingPopulationTruncated
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    LocalIndexingSessionCapture,
)

from tests.unit.test_public_solution_encoding import public_entry


@dataclass(frozen=True)
class SyntheticIntent:
    maximum_candidates: int = 1024
    source_revision_ids: tuple[str, ...] = ()


def case(monkeypatch, count):
    example = public_entry()
    owner = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    intent, authority, session, parent = SyntheticIntent(), Mock(), Mock(), Mock()
    authority.authorize_scope.return_value = object()
    members = tuple(("itemrev_" + f"{i:032x}", "analysisrun_" + f"{i:032x}") for i in range(count))
    selections, readers = [], []

    def statement(scope, *, after_source_revision_id):
        assert scope.maximum_candidates == 128 and intent.maximum_candidates == 1024
        return after_source_revision_id

    def execute(after):
        return tuple(row for row in members if after is None or row[0] > after)[:129]

    def reader(actual_session, settings):
        assert actual_session is session and settings is parent.settings
        value = Mock()
        readers.append(value)
        return value

    def capture(actual_session, selected, **kwargs):
        assert actual_session is session and kwargs["authority"] is authority
        assert kwargs["artifact_reader"] is readers[-1]
        keys = selected.source_revision_ids
        assert 0 < len(keys) <= 128
        selections.append(keys)
        key_set = set(keys)
        sources = tuple(
            AdmittedInferenceTransferSource(
                run, example.source.model_copy(update={"item_revision_id": key})
            )
            for key, run in members
            if key in key_set
        )
        return LocalIndexingSessionCapture(
            selected, AdmittedInferenceTransferCorpus((), (), False, len(keys), sources), ()
        )

    monkeypatch.setattr(module, "candidate_source_page_statement", statement)
    monkeypatch.setattr(module, "PinnedArtifactReadContext", reader)
    monkeypatch.setattr(owner, "capture_indexing_in_session", capture)
    session.execute.side_effect = execute
    return NS(**locals())


def run(value):
    return value.owner._capture_indexing_population_pages(
        value.session, value.intent, authority=value.authority, artifact_reader=value.parent
    )


@pytest.mark.parametrize("count", [0, 677, 1024])
def test_bounded_readers_preserve_complete_legacy_population(monkeypatch, count):
    value = case(monkeypatch, count)
    result = run(value)
    assert result.scope is value.intent and not result.corpus.truncated
    assert (
        tuple((row.source.item_revision_id, row.analysis_run_id) for row in result.corpus.sources)
        == value.members
    )
    assert result.corpus.missing_solution_reports == count
    assert sum(map(len, value.selections)) == count
    assert len({id(reader) for reader in value.readers}) == len(value.selections)
    for reader in value.readers:
        reader.revalidate_provenance.assert_called_once()
    value.authority.authorize_scope.assert_called_with(value.session, value.intent)
    assert value.authority.authorize_scope.call_count == 2


def test_legacy_limit_is_not_silently_expanded_or_truncated(monkeypatch):
    value = case(monkeypatch, 1025)
    with pytest.raises(InferenceTransferServiceError, match="POPULATION_TRUNCATED"):
        run(value)


def test_final_membership_change_is_rejected(monkeypatch):
    value = case(monkeypatch, 256)
    original = value.session.execute.side_effect
    calls = 0

    def changed(after):
        nonlocal calls
        calls += 1
        rows = original(after)
        return rows[:-1] if calls > 2 else rows

    value.session.execute.side_effect = changed
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        run(value)


def test_only_known_population_truncation_becomes_capacity_exception():
    def truncated():
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED")

    with pytest.raises(EmbeddingPopulationTruncated):
        CatalogEmbeddingRegistryVerifier._guard(truncated)


def test_full_service_population_delegates_to_bounded_owner_after_authorization():
    from tests.unit.inference_transfer_embedding_fixtures import view_recipe

    owner = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    intent = NS(source_revision_ids=(), analysis_run_ids=(), recipe=view_recipe())
    authority, reader, session = Mock(), Mock(), Mock()
    expected = LocalIndexingSessionCapture(intent)
    owner._capture_indexing_population_pages = Mock(return_value=expected)
    assert (
        owner.capture_indexing_in_session(
            session, intent, authority=authority, artifact_reader=reader
        )
        is expected
    )
    authority.authorize_scope.assert_called_once_with(session, intent)
    owner._capture_indexing_population_pages.assert_called_once_with(
        session, intent, authority=authority, artifact_reader=reader
    )
