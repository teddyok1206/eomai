"""Human QUERY shares strict interpretation, never authority or a different scope."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import public_solution_index_read_set as module
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_identifiers import canonical_json_bytes

from tests.unit.test_inference_transfer_candidate_admission import admission_scope
from tests.unit.test_public_solution_encoding import public_entry, public_recipe


@pytest.fixture
def case(monkeypatch):
    scope, recipe = admission_scope(), public_recipe()
    session = Mock(info={}, new=set(), dirty=set(), deleted=set())
    root = NS(is_active=True)
    session.get_transaction.return_value = root
    session.in_nested_transaction.return_value = False
    session.get_nested_transaction.return_value = None
    reader = Mock(settings=NS(nas_artifact_root="synthetic"))
    entry = public_entry()
    value = CapturedPublicSolutionSources(
        (entry,), (), (entry.source.item_revision_id,), scope, None
    )
    capture, reauthorize = Mock(return_value=value), Mock(return_value=scope)
    observation = Mock(return_value="sha256:" + "a" * 64)
    monkeypatch.setattr(module, "observe_public_solution_population_dependencies", observation)
    state = NS(**locals())

    def run():
        return module.capture_public_solution_query_population(
            session,
            state.scope,
            state.recipe,
            reader=reader,
            maximum_sources=16384,
            capture=capture,
            reauthorize=reauthorize,
        )

    state.run = run
    return state


def test_query_interprets_once_and_rechecks_current_closure_authority_and_provenance(case):
    before = canonical_json_bytes(case.entry)
    for _ in range(4):
        assert case.run() is case.value
    assert case.capture.call_count == 1
    assert case.observation.call_count == 5
    assert case.reauthorize.call_count == case.reader.revalidate_provenance.call_count == 4
    assert canonical_json_bytes(case.entry) == before


@pytest.mark.parametrize("change", ("dependency", "authority", "provenance", "thread", "nested"))
def test_query_reuse_rejects_changed_or_invalid_read_boundary(case, monkeypatch, change):
    case.run()
    if change == "dependency":
        case.observation.return_value = "sha256:" + "b" * 64
    elif change == "authority":
        case.reauthorize.side_effect = ValueError("permission revoked")
    elif change == "provenance":
        case.reader.revalidate_provenance.side_effect = ValueError("hash mismatch")
    elif change == "thread":
        monkeypatch.setattr(module, "get_ident", lambda: -1)
    else:
        case.session.in_nested_transaction.return_value = True
        case.session.get_nested_transaction.return_value = NS(is_active=True)
    with pytest.raises(ValueError):
        case.run()
    assert case.capture.call_count == 1


@pytest.mark.parametrize("change", ("operator", "recipe", "root", "settings"))
def test_query_never_reuses_a_different_exact_capture(case, change):
    case.run()
    if change == "operator":
        case.scope = replace(case.scope, requested_by="operator_" + "f" * 32)
        case.value = replace(case.value, scope=case.scope)
        case.capture.return_value, case.reauthorize.return_value = case.value, case.scope
    elif change == "recipe":
        case.recipe = case.recipe.model_copy(update={"maximum_text_bytes": 1024})
    elif change == "root":
        case.root.is_active = False
        case.session.get_transaction.return_value = NS(is_active=True)
    else:
        case.reader.settings = NS(nas_artifact_root="another-exact-root")
    assert case.run() is case.value
    assert case.capture.call_count == 2


@pytest.mark.parametrize("fault", ("torn", "capture_failure", "root_changed", "wrong_scope"))
def test_query_failed_initial_capture_does_not_seed_reuse(case, fault):
    if fault == "torn":
        case.observation.side_effect = ("before", "after")
    elif fault == "capture_failure":
        case.capture.side_effect = ValueError("report invalid")
    elif fault == "wrong_scope":
        case.capture.return_value = replace(case.value, scope=NS())
    else:

        def changed():
            case.session.get_transaction.return_value = NS(is_active=True)
            return case.value

        case.capture.side_effect = changed
    with pytest.raises(ValueError):
        case.run()
    assert not case.session.info


def test_query_dirty_context_uses_strict_path_not_cached_capture(case):
    case.run()
    case.session.dirty = {"unflushed"}
    case.run()
    case.run()
    assert case.capture.call_count == 3
    assert not case.session.info
