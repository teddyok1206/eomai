"""Actual control bytes; explicitly synthetic current-read/native Identity and source seams."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_identity_service import OperatorAuthorizationFenceError
from eom_workflow_runner import reference_query_source_read as module
from eom_workflow_runner.reference_query_source_read import CatalogReferenceQueryReadOwner

from tests.unit.test_reference_query_owner_admission import source as source


def read_owner(source, monkeypatch):
    observations = []
    state = SimpleNamespace(denied=False)

    def current(session, operator_id):
        root = session.get_transaction()
        assert root is not None and root.is_active
        observations.append(session)
        if state.denied or operator_id != source.request.operator_audit.operator_id:
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    owner = CatalogReferenceQueryReadOwner(
        source.publisher.engine,
        source.owner.configuration,
        identity_fence=SimpleNamespace(fence_current_operator=current),
        settings=source.owner.settings,
    )
    # Scope/index behavior remains explicitly synthetic; control file bytes are real.
    for name in ("authorize_scope", "prepare_reference_query_anchor_in_session"):
        monkeypatch.setattr(owner.catalog, name, getattr(source.owner.catalog, name))
    return owner, state, observations


def test_fresh_explicit_read_authority_does_not_reuse_the_native_execution_capture(
    source, monkeypatch
):
    with source.publisher.sessions.begin() as session:
        expected = source.owner.resolve_sources(session, source.request)
    owner, _state, observations = read_owner(source, monkeypatch)
    source.deny = True  # The original native captured-session port is unavailable.
    with source.publisher.sessions.begin() as session:
        with pytest.raises(OperatorAuthorizationFenceError):
            source.owner.resolve_sources(session, source.request)
        assert owner.resolve_sources(session, source.request) == expected
        assert observations == [session, session]
    assert not any(
        hasattr(owner, name)
        for name in (
            "resolve_submission",
            "resolve_claim",
            "fence_mutation",
            "resolve_mutation_sources",
            "resolve_execution_sources",
        )
    )
    assert source.owner.identity is not owner.identity


def test_missing_read_authority_never_constructs_a_registry_or_infers_a_user(source, monkeypatch):
    monkeypatch.setattr(
        module,
        "CatalogEmbeddingRegistryVerifier",
        lambda *_a, **_kw: pytest.fail("missing current authority must fail first"),
    )
    with pytest.raises(ValueError, match="REFERENCE_QUERY_READ_AUTHORITY_UNAVAILABLE"):
        CatalogReferenceQueryReadOwner(
            source.publisher.engine,
            source.owner.configuration,
            identity_fence=None,
            settings=source.owner.settings,
        )


@pytest.mark.parametrize("late", (False, True))
def test_denied_current_read_authority_stays_denied_without_an_execution_fallback(
    source, monkeypatch, late
):
    owner, state, observations = read_owner(source, monkeypatch)
    if late:
        original = owner.catalog.prepare_reference_query_anchor_in_session

        def revoke(*args):
            result = original(*args)
            state.denied = True
            return result

        monkeypatch.setattr(owner.catalog, "prepare_reference_query_anchor_in_session", revoke)
    else:
        state.denied = True
        monkeypatch.setattr(
            module,
            "PinnedArtifactReadContext",
            lambda *_a: pytest.fail("current denial must precede materialization"),
        )
    with source.publisher.sessions.begin() as session:
        with pytest.raises(OperatorAuthorizationFenceError):
            owner.resolve_sources(session, source.request)
        assert observations == [session] * (2 if late else 1)


def test_existing_public_configuration_and_derivation_imports_remain_identical():
    from eom_workflow_runner import reference_query_owner_admission as native

    for name in (
        "ReferenceQueryOwnerConfiguration",
        "ResolvedReferenceQuerySources",
        "ResolvedCompletedReferenceQuerySources",
        "build_reference_query_native_input",
        "validate_current_reference_query_input",
    ):
        assert getattr(native, name) is getattr(module, name)
