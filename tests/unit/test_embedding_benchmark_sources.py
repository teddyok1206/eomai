"""Synthetic current-source composition; no live Identity, DB, NAS, tokenizer or model."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkTextRow,
    benchmark_input_set_sha256,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.inference_transfer_experiment import experiment_view_text, profile_key
from eom_catalog_service import embedding_benchmark_sources as module
from eom_catalog_service.embedding_benchmark_sources import CatalogBenchmarkSourceAdmission
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import owner_request, staged_inputs
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_experiment_fixtures import entry

ACTOR = "operator_" + "1" * 32


@pytest.fixture
def admitted(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    entries = tuple(entry(seed) for seed in "abcdef")
    by_profile = {profile_key(source.profile): source for source in owner_request().sources}
    entries_by_key = {
        (
            value.profile.profile_id,
            value.profile.profile_revision_id,
            value.profile.profile_sha256,
        ): value
        for value in entries
    }

    def projected(row: BenchmarkTextRow) -> dict[str, object]:
        text = experiment_view_text(entries_by_key[profile_key(row.row.profile)], row.row.view)
        assert text is not None and text.strip()
        body = row.model_dump(mode="json")
        body["text"] = text
        body["row"]["input_text_sha256"] = content_sha256(text)
        body["row"] = seal(body["row"], "row_sha256")
        return body

    original = staged_inputs()
    documents = tuple(BenchmarkTextRow.model_validate(projected(row)) for row in original.documents)
    queries = tuple(BenchmarkTextRow.model_validate(projected(row)) for row in original.queries)
    body = original.model_dump(mode="json")
    body.update(
        documents=[row.model_dump(mode="json") for row in documents],
        queries=[row.model_dump(mode="json") for row in queries],
        input_set_sha256=benchmark_input_set_sha256(documents, queries, original.view_recipe),
    )
    inputs = BenchmarkStagedInputs.model_validate(body)
    request_body = owner_request().model_dump(mode="json")
    request_body.update(
        operator_audit_id=ACTOR,
        document_rows=[row.row.model_dump(mode="json") for row in documents],
        query_rows=[row.row.model_dump(mode="json") for row in queries],
        input_set_sha256=inputs.input_set_sha256,
    )
    request_body["input_manifest"]["sha256"] = sha256_bytes(
        embedding_device_benchmark_bytes(inputs)
    )
    request = BenchmarkOwnerRequest.model_validate(seal(request_body, "request_sha256"))
    corpus = AdmittedInferenceTransferCorpus(
        profiles=tuple(value.profile for value in entries),
        graph_scores=(),
        truncated=False,
        missing_solution_reports=0,
        sources=tuple(
            AdmittedInferenceTransferSource(
                by_profile[key].solution_evidence.base_analysis_run_id, by_profile[key].source
            )
            for key in sorted(by_profile)
        ),
    )
    capture = InferenceTransferSessionCapture(Mock(), corpus, entries)
    source = Mock()
    source.capture_in_session.return_value = capture
    reader = Mock()
    reader.read_member.return_value = embedding_device_benchmark_bytes(inputs)
    reader_factory = Mock(return_value=reader)
    monkeypatch.setattr(module, "PinnedArtifactReadContext", reader_factory)
    owner = object.__new__(CatalogBenchmarkSourceAdmission)
    owner._identity = Mock(capture=SimpleNamespace(operator_id=ACTOR))
    owner._sources = source
    owner._settings = Mock()
    session = Mock()
    session.in_nested_transaction.return_value = False
    return SimpleNamespace(
        owner=owner,
        session=session,
        reader=reader,
        factory=reader_factory,
        capture=capture,
        request=request,
        inputs=inputs,
    )


def test_exact_six_sources_and_committed_input_share_the_official_root_reader(admitted):
    value = admitted
    assert value.owner.resolve_in_session(value.session, value.request) == value.inputs
    call = value.owner._sources.capture_in_session.call_args
    command = call.args[1]
    assert command.actor_id == ACTOR and command.maximum_candidates == 6
    assert command.graph_snapshot == value.request.graph_snapshot
    assert command.access_policy_revision_id == value.request.policy_revision_id
    assert command.access_policy_sha256 == value.request.policy_sha256
    assert command.source_revision_ids == tuple(
        sorted(s.source.item_revision_id for s in value.request.sources)
    )
    assert call.kwargs["artifact_reader"] is value.reader
    assert call.kwargs["identity_fence"] is value.owner._identity
    assert value.owner._identity.fence_current_operator.call_count == 2
    assert value.reader.read_member.call_count == 1
    assert (
        value.reader.read_member.call_args.kwargs["sha256"] == value.request.input_manifest.sha256
    )


def test_audit_actor_is_not_authentication(admitted):
    value = admitted
    body = value.request.model_dump(mode="json")
    body["operator_audit_id"] = "operator_" + "f" * 32
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError, match="OPERATOR_MISMATCH"):
        value.owner.resolve_in_session(value.session, request)
    value.factory.assert_not_called()
    value.owner._sources.capture_in_session.assert_not_called()


def test_savepoint_is_not_a_new_authorization_root(admitted):
    value = admitted
    value.session.in_nested_transaction.return_value = True
    with pytest.raises(ValueError, match="ROOT_TRANSACTION"):
        value.owner.resolve_in_session(value.session, value.request)
    value.factory.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    ("truncated", "missing_report", "extra", "missing", "duplicate", "source", "graph", "report"),
)
def test_changed_canonical_population_is_rejected_before_input_member_read(admitted, fault):
    value = admitted
    capture = value.capture
    if fault == "truncated":
        corpus = replace(capture.corpus, truncated=True)
    elif fault == "missing_report":
        corpus = replace(capture.corpus, missing_solution_reports=1)
    elif fault == "extra":
        corpus = replace(
            capture.corpus, profiles=(*capture.corpus.profiles, capture.corpus.profiles[0])
        )
    elif fault == "missing":
        corpus = replace(capture.corpus, profiles=capture.corpus.profiles[:-1])
    elif fault == "duplicate":
        corpus = replace(capture.corpus, profiles=(capture.corpus.profiles[0],) * 6)
    else:
        changed = capture.entries[0].profile.model_dump(mode="json")
        basis = changed["source_basis"]
        if fault == "source":
            basis["source"]["item_revision_id"] = "itemrev_" + "0" * 32
        elif fault == "graph":
            basis["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
        else:
            basis["solution_evidence"]["base_analysis_run_id"] = "analysisrun_" + "0" * 32
            basis["solution_evidence"] = seal(basis["solution_evidence"], "pointer_sha256")
        from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile

        profile = InferenceTransferProfile.model_validate(seal(changed, "profile_sha256"))
        altered = capture.entries[0].model_copy(update={"profile": profile})
        capture = replace(capture, entries=(altered, *capture.entries[1:]))
        corpus = capture.corpus
    value.owner._sources.capture_in_session.return_value = replace(capture, corpus=corpus)
    with pytest.raises(ValueError):
        value.owner.resolve_in_session(value.session, value.request)
    value.reader.read_member.assert_not_called()


@pytest.mark.parametrize("raw", (b"{}", b"not-json", b" ", None))
def test_missing_changed_or_noncanonical_committed_input_is_not_replaced(admitted, raw):
    value = admitted
    value.reader.read_member.return_value = (
        embedding_device_benchmark_bytes(value.inputs) + b"\n" if raw is None else raw
    )
    with pytest.raises(ValueError):
        value.owner.resolve_in_session(value.session, value.request)


def test_rehashed_staged_text_must_still_equal_canonical_source_projection(admitted):
    value = admitted
    original = staged_inputs()
    # This is a closed valid contract with deliberately different synthetic text.
    body = owner_request().model_dump(mode="json")
    body["operator_audit_id"] = ACTOR
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    value.reader.read_member.return_value = embedding_device_benchmark_bytes(original)
    with pytest.raises(ValueError, match="SOURCE_PIN_MISMATCH"):
        value.owner.resolve_in_session(value.session, request)


@pytest.mark.parametrize("late", (False, True))
def test_permission_revocation_is_not_cached_or_a_model_retry(admitted, late):
    value = admitted
    value.owner._identity.fence_current_operator.side_effect = (
        [None, ValueError("REVOKED")] if late else ValueError("REVOKED")
    )
    with pytest.raises(ValueError, match="REVOKED"):
        value.owner.resolve_in_session(value.session, value.request)
    assert value.reader.read_member.call_count == int(late)


def test_constructor_does_not_accept_an_actor_string_instead_of_identity_capture():
    with pytest.raises(ValueError):
        CatalogBenchmarkSourceAdmission(Mock(), capture=ACTOR, session_fence=Mock())


def test_mutation_context_rechecks_scope_without_rereading_input(admitted):
    value = admitted
    with value.owner.admit_in_session(value.session, value.request) as inputs:
        assert inputs == value.inputs
        assert value.reader.read_member.call_count == 1
    call = value.owner._sources.capture_in_session.call_args
    assert call.kwargs["phase"] is module.InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
    assert value.owner._sources.capture_in_session.call_count == 2
    assert value.reader.read_member.call_count == 1
    assert value.owner._identity.fence_current_operator.call_count == 3


@pytest.mark.parametrize("fault", ("scope", "root", "nested", "expired"))
def test_late_mutation_context_failure_returns_no_admitted_result(admitted, fault):
    value = admitted
    with pytest.raises(ValueError), value.owner.admit_in_session(value.session, value.request):
        if fault == "scope":
            value.owner._sources.capture_in_session.side_effect = ValueError("REVOKED")
        elif fault == "root":
            value.session.get_transaction.return_value = Mock()
        elif fault == "nested":
            value.session.in_nested_transaction.return_value = True
        else:
            value.owner._identity.fence_current_operator.side_effect = ValueError("EXPIRED")
