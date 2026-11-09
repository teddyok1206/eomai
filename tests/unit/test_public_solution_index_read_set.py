"""Strict source interpretation once, current fences on every INDEX root read."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import public_solution_index_read_set as module
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_identifiers import canonical_json_bytes

from tests.unit.test_public_solution_encoding import public_entry


@pytest.fixture
def case(monkeypatch):
    # SQL and IAM are separate leaves here; real PostgreSQL observations have a
    # disposable suite. No synthetic identity is used for production reads.
    scope = NS(scope="exact-service-intent")
    session = Mock(info={})
    root = NS(is_active=True)
    session.get_transaction.return_value = root
    session.in_nested_transaction.return_value = False
    reader = Mock(settings=NS(nas_artifact_root="synthetic"))
    entry = public_entry()
    value = CapturedPublicSolutionSources(
        (entry,), (), (entry.source.item_revision_id,), scope, None
    )
    capture = Mock(return_value=value)
    reauthorize = Mock(return_value=scope)
    observation = Mock(return_value="sha256:" + "a" * 64)
    monkeypatch.setattr(module, "observe_public_solution_population_dependencies", observation)

    def run():
        return module.capture_public_solution_index_population(
            session,
            scope,
            reader=reader,
            maximum_sources=16384,
            capture=capture,
            reauthorize=reauthorize,
        )

    return NS(**locals())


def test_repeated_reads_preserve_exact_entries_and_each_current_fence(case):
    before = canonical_json_bytes(case.entry)
    for _ in range(5):
        assert case.run() is case.value
    assert case.capture.call_count == 1
    assert case.observation.call_count == 6  # before/after first, then each read
    assert case.reauthorize.call_count == 5
    assert case.reader.revalidate_provenance.call_count == 5
    assert canonical_json_bytes(case.entry) == before


def test_changed_dependency_never_silently_recaptures_or_reuses(case):
    case.run()
    case.observation.return_value = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        case.run()
    assert case.capture.call_count == 1


def test_torn_initial_capture_is_not_retained(case):
    case.observation.side_effect = ["before", "after"]
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        case.run()
    assert not case.session.info


@pytest.mark.parametrize("fault", ["denied", "changed", "provenance"])
def test_cache_hit_keeps_authorization_and_provenance_fences(case, fault):
    case.run()
    if fault == "denied":
        case.reauthorize.side_effect = ValueError("permission revoked")
    elif fault == "changed":
        case.reauthorize.return_value = NS(scope="changed")
    else:
        case.reader.revalidate_provenance.side_effect = ValueError("producer revoked")
    with pytest.raises(ValueError):
        case.run()
    assert case.capture.call_count == 1


def test_new_transaction_requires_a_new_strict_capture(case):
    case.run()
    case.root.is_active = False
    case.session.get_transaction.return_value = NS(is_active=True)
    assert case.run() is case.value
    assert case.capture.call_count == 2


@pytest.mark.parametrize("fault", ["inactive", "nested", "thread", "reader"])
def test_invalid_owning_root_or_reader_is_rejected(case, monkeypatch, fault):
    case.run()
    if fault == "inactive":
        case.root.is_active = False
    elif fault == "nested":
        case.session.in_nested_transaction.return_value = True
    elif fault == "thread":
        monkeypatch.setattr(module, "get_ident", lambda: -1)
    else:
        case.reader.require_session.side_effect = ValueError("wrong root")
    with pytest.raises(ValueError):
        case.run()
    assert case.capture.call_count == 1


def test_failed_capture_or_wrong_scope_cannot_seed_reuse(case):
    case.capture.side_effect = ValueError("hash mismatch")
    with pytest.raises(ValueError, match="hash mismatch"):
        case.run()
    assert not case.session.info
    case.capture.side_effect = None
    case.capture.return_value = replace(case.value, scope=NS(scope="another"))
    with pytest.raises(ValueError, match="READ_SET_INVALID"):
        case.run()
    assert not case.session.info


def test_scope_change_is_a_different_capture_not_an_implicit_latest_substitution(case):
    case.run()
    changed = NS(scope="different-explicit-selection")
    new_value = replace(case.value, scope=changed)
    assert (
        module.capture_public_solution_index_population(
            case.session,
            changed,
            reader=case.reader,
            maximum_sources=16384,
            capture=lambda: new_value,
            reauthorize=lambda: changed,
        )
        is new_value
    )
    assert case.run() is case.value  # single slot, not a growing cache of scopes
    assert case.capture.call_count == 2
