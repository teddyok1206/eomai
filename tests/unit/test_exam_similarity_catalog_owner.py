"""Concrete C5 owner orchestration with synthetic IAM/source/index seams, not live PASS."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_registry_catalog_adapter as module
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryServiceCaller,
)
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError

from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_exam_similarity_observation import exam_case, exam_entries
from tests.unit.test_similarity_context_service import CALLER


@pytest.mark.parametrize(
    "fault", (None, "revoked_report", "missing_member", "scope_denied", "root_switch", "no_index")
)
def test_exact_cohort_same_root_decode_window_and_fresh_full_end_fence(owner, monkeypatch, fault):
    verifier, session, _command, _index, _binding, _scope, _root = owner
    request, prepared, reads = exam_case(available=24, indexes=fault != "no_index")
    entries = exam_entries()[:24]
    original = verifier.sources.capture_in_session.side_effect
    monkeypatch.setattr(session, "no_autoflush", nullcontext(), raising=False)
    monkeypatch.setattr(session, "in_nested_transaction", lambda: False, raising=False)
    monkeypatch.setattr(verifier, "sessions", Mock(side_effect=AssertionError("new root")))
    phases, windows = [], []

    def capture(actual_session, command, recipe, **options):
        assert actual_session is session and command.actor_id == CALLER.operator_id
        assert command.top_k == command.maximum_candidates == 25
        assert command.source_revision_ids == tuple(
            sorted(member.item_revision_id for member in request.cohort.members)
        )
        if fault == "scope_denied":
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        value = original(actual_session, command, recipe, **options)
        phase = options["phase"].value
        phases.append(phase)
        if phase == "AUTHORIZE_SCOPE":
            return value
        admitted = prepared[:-1] if fault == "missing_member" else prepared
        current_entries = (
            entries[:-1]
            if fault == "revoked_report" and phases.count("CAPTURE_POPULATION") == 2
            else entries
        )
        return replace(
            value,
            corpus=AdmittedInferenceTransferCorpus(
                tuple(entry.profile for entry in current_entries),
                (),
                False,
                25 - len(current_entries),
                tuple(
                    AdmittedInferenceTransferSource("analysisrun_" + "1" * 32, v.source)
                    for v in admitted
                ),
            ),
            entries=current_entries,
        )

    def read(actual_session, caller, intent, read_owner):
        assert actual_session is session and caller == CALLER
        window = read_owner._similarity_read_window
        windows.append(window)
        read_owner.authorize_scope(actual_session, caller, intent.scope)
        _reader, captured = read_owner._capture(
            actual_session,
            caller,
            intent.scope,
            module.InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
        )
        assert captured is window.capture
        read_owner.authorize_scope(actual_session, caller, intent.scope)
        if fault == "root_switch" and len(windows) == 3:
            changed_root = SimpleNamespace(is_active=True)
            monkeypatch.setattr(session, "get_transaction", lambda: changed_root)
        return replace(
            next(r for r in reads if r.intent.selection == intent.selection), intent=intent
        )

    monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
    monkeypatch.setattr(module, "read_pinned_embedding_index", read)
    if fault in {None, "no_index"}:
        result = verifier.observe_exam_similarity_in_session(session, CALLER, request)
        assert result.status == ("EMPTY" if fault == "no_index" else "PARTIAL")
        assert len(result.members) == 25
        assert len(windows) == (0 if fault == "no_index" else 3)
        assert all(window is windows[0] for window in windows)
        assert phases.count("CAPTURE_POPULATION") == 2
        assert phases.count("AUTHORIZE_SCOPE") == (0 if fault == "no_index" else 9)
    else:
        with pytest.raises(SimilarityContextReadError) as error:
            verifier.observe_exam_similarity_in_session(session, CALLER, request)
        assert (
            error.value.code
            == {
                "revoked_report": "SOURCE_REVOKED",
                "missing_member": "SOURCE_POINTER_INVALID",
                "scope_denied": "SOURCE_ACCESS_DENIED",
                "root_switch": "AUTHORITY_UNAVAILABLE",
            }[fault]
        )
        if fault not in {"revoked_report", "root_switch"}:
            assert not windows
    verifier.sessions.assert_not_called()


@pytest.mark.parametrize("fault", ("missing_root", "nested", "service_caller", "recipe"))
def test_no_authority_shortcuts_or_consumer_gate_weakening(owner, monkeypatch, fault):
    verifier, session, *_ = owner
    request, _, _ = exam_case(indexes=False)
    monkeypatch.setattr(session, "in_nested_transaction", lambda: fault == "nested", raising=False)
    if fault == "missing_root":
        monkeypatch.setattr(session, "get_transaction", lambda: None)
    if fault == "recipe":
        verifier.configuration = replace(verifier.configuration, source_classes=("APPROVED_ITEM",))
    caller = (
        EmbeddingRegistryServiceCaller("indexingservice_" + "1" * 32)
        if fault == "service_caller"
        else CALLER
    )
    with pytest.raises(SimilarityContextReadError):
        verifier.observe_exam_similarity_in_session(session, caller, request)
    verifier.sources.capture_in_session.assert_not_called()
