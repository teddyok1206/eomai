"""Real selected-source dispatch with synthetic current source/IAM capture fixtures."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_materials import validate_similarity_materials
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_similarity_materials_contracts import materials_case


def selected_case(
    owner, monkeypatch, *, fault=None, missing_anchor=False, purpose="PAST_EXAM_VARIATION"
):
    verifier, session, _command, _index, _binding, scope, _root = owner
    context, anchor, entries = materials_case(count=2, missing_anchor=missing_anchor)
    raw = context.model_dump(mode="json")
    raw["request"]["source_classes"] = ["PAST_EXAM"]
    raw["request"]["consumer_purpose"] = purpose
    raw["request"] = seal(raw["request"], "request_sha256")
    context = parse_similarity_context(seal(raw, "context_sha256"))
    values = (
        entries
        if anchor is None
        else (entries[0].model_copy(update={"profile": anchor, "content": None}), *entries)
    )
    calls = []

    def capture(actual_session, command, recipe, **options):
        assert actual_session is session
        options["artifact_reader"].require_session(actual_session)
        options["identity_fence"].fence_current_operator(actual_session, command.actor_id)
        calls.append(command)
        selected = values
        if fault == "missing":
            selected = selected[:-1]
        elif fault == "duplicate":
            selected = (*selected, selected[-1])
        elif fault == "reversed":
            selected = tuple(reversed(selected))
        elif fault == "changed_profile":
            from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry

            body = selected[-1].model_dump(mode="json")
            body["profile"]["claims"][0]["text"] += " 합성 변경"
            body["profile"] = seal(body["profile"], "profile_sha256")
            selected = (*selected[:-1], StagedExperimentEntry.model_validate(body))
        corpus = AdmittedInferenceTransferCorpus(
            tuple(entry.profile for entry in selected),
            (),
            fault == "truncated",
            0,
            tuple(
                AdmittedInferenceTransferSource(
                    entry.profile.source_basis.solution_evidence.base_analysis_run_id,
                    entry.profile.source_basis.source,
                )
                for entry in selected
            ),
        )
        return InferenceTransferSessionCapture(scope, corpus, selected)

    monkeypatch.setattr(verifier.sources, "capture_in_session", Mock(side_effect=capture))
    return verifier, session, context, entries, calls


@pytest.mark.parametrize("purpose", ("ITEM_AUTHORING", "ITEM_REVIEW"))
def test_authoring_reference_materials_use_same_actual_caller_and_selected_source_boundary(
    owner, monkeypatch, purpose
):
    verifier, session, context, entries, calls = selected_case(owner, monkeypatch, purpose=purpose)
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    materials = verifier.read_similarity_materials_in_session(session, caller, context)
    assert validate_similarity_materials(materials, context) == materials
    assert materials.entries == entries
    assert context.request.consumer_purpose == purpose
    assert len(calls) == 1 and calls[0].actor_id == caller.operator_id
    assert calls[0].source_classes == ("PAST_EXAM",)


@pytest.mark.parametrize("missing_anchor", (False, True))
@pytest.mark.parametrize("reverse_capture", (False, True))
def test_one_selected_batch_reuses_existing_authority_and_context_order(
    owner, monkeypatch, missing_anchor, reverse_capture
):
    verifier, session, context, entries, calls = selected_case(
        owner,
        monkeypatch,
        fault="reversed" if reverse_capture else None,
        missing_anchor=missing_anchor,
    )
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    materials = verifier.read_similarity_materials_in_session(session, caller, context)
    assert validate_similarity_materials(materials, context) == materials
    assert materials.entries == entries
    assert (materials.anchor_profile is None) == missing_anchor
    (command,) = calls
    expected = {candidate.source.item_revision_id for candidate in context.candidates}
    if not missing_anchor:
        expected.add(context.request.anchor.source.item_revision_id)
    assert command.source_revision_ids == tuple(sorted(expected))
    assert command.actor_id == caller.operator_id
    assert command.graph_snapshot == context.request.graph_snapshot
    assert command.access_policy_revision_id == context.request.policy_revision_id
    assert command.access_policy_sha256 == context.request.policy_sha256
    assert command.source_classes == ("PAST_EXAM",)
    assert (
        verifier.sources.capture_in_session.call_args.kwargs["phase"]
        is InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
    )


@pytest.mark.parametrize("fault", ("missing", "duplicate", "changed_profile", "truncated"))
def test_current_selected_projection_drift_never_becomes_partial_success(owner, monkeypatch, fault):
    verifier, session, context, _entries, calls = selected_case(owner, monkeypatch, fault=fault)
    with pytest.raises(SimilarityContextReadError):
        verifier.read_similarity_materials_in_session(
            session, EmbeddingRegistryCaller("operator_" + "1" * 32), context
        )
    assert len(calls) == 1


def test_missing_actual_fence_denies_before_selected_source_read(owner, monkeypatch):
    verifier, session, context, _entries, calls = selected_case(owner, monkeypatch)
    verifier.identity_fence = None
    with pytest.raises(SimilarityContextReadError) as captured:
        verifier.read_similarity_materials_in_session(
            session, EmbeddingRegistryCaller("operator_" + "1" * 32), context
        )
    assert captured.value.code == "AUTHORITY_UNAVAILABLE"
    assert not calls


@pytest.mark.parametrize("missing_fence", (False, True))
def test_empty_materials_still_use_current_official_capture(owner, monkeypatch, missing_fence):
    verifier, session, context, _entries, calls = selected_case(
        owner, monkeypatch, missing_anchor=True
    )
    raw = context.model_dump(mode="json")
    raw.update(status="UNAVAILABLE", candidates=[])
    raw["limitations"].append("NO_RELATED_CANDIDATES")
    context = parse_similarity_context(seal(raw, "context_sha256"))
    if missing_fence:
        verifier.identity_fence = None
        with pytest.raises(SimilarityContextReadError):
            verifier.read_similarity_materials_in_session(
                session, EmbeddingRegistryCaller("operator_" + "1" * 32), context
            )
        assert not calls
        return
    materials = verifier.read_similarity_materials_in_session(
        session, EmbeddingRegistryCaller("operator_" + "1" * 32), context
    )
    assert not materials.entries and materials.anchor_profile is None
    assert len(calls) == 1 and calls[0].source_revision_ids == ()


def test_unsupported_consumer_does_not_borrow_variation_authority(owner, monkeypatch):
    verifier, session, context, _entries, calls = selected_case(owner, monkeypatch)
    raw = context.model_dump(mode="json")
    raw["request"]["consumer_purpose"] = "GENERAL_CHAT_READ"
    raw["request"] = seal(raw["request"], "request_sha256")
    context = parse_similarity_context(seal(raw, "context_sha256"))
    with pytest.raises(SimilarityContextReadError) as captured:
        verifier.read_similarity_materials_in_session(
            session, EmbeddingRegistryCaller("operator_" + "1" * 32), context
        )
    assert captured.value.code == "AUTHORITY_UNAVAILABLE"
    assert not calls
