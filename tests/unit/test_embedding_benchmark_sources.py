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
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.knowledge import ApprovedPastExamItemKnowledgeSourceV3
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
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_v3_record

ACTOR = "operator_" + "1" * 32


@pytest.fixture
def admitted(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    entries = tuple(entry(seed) for seed in "abcdef")
    # Real past-exam sources use this member naming; the profile still pins V2 core identity.
    normalized = []
    for value in entries:
        body = value.profile.model_dump(mode="json")
        body["source_basis"]["source"]["artifact_member"].update(
            materialized_path="source/item-content.json", logical_name="item-content.json"
        )
        profile = InferenceTransferProfile.model_validate(seal(body, "profile_sha256"))
        content = value.content.model_copy(
            update={"original_source": profile.source_basis.source.artifact_member}
        )
        normalized.append(value.model_copy(update={"profile": profile, "content": content}))
    entries = tuple(normalized)
    source_by_revision = {
        source.source.item_revision_id: source for source in owner_request().sources
    }
    by_profile = {
        profile_key(
            InferenceTransferProfilePointer.from_profile(value.profile)
        ): source_by_revision[value.profile.source_basis.source.item_revision_id].model_copy(
            update={
                "profile": InferenceTransferProfilePointer.from_profile(value.profile),
                "source": value.profile.source_basis.source,
            }
        )
        for value in entries
    }
    entries_by_id = {value.profile.profile_id: value for value in entries}

    def projected(row: BenchmarkTextRow) -> dict[str, object]:
        value = entries_by_id[row.row.profile.profile_id]
        text = experiment_view_text(value, row.row.view)
        assert text is not None and text.strip()
        body = row.model_dump(mode="json")
        body["text"] = text
        body["row"]["profile"] = InferenceTransferProfilePointer.from_profile(
            value.profile
        ).model_dump(mode="json")
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
        sources=[by_profile[key].model_dump(mode="json") for key in sorted(by_profile)],
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


def _with_visual_admitted_source(value, *, pin_visual=False):
    selected = value.request.sources[0]
    source = ApprovedPastExamItemKnowledgeSourceV3.model_validate(
        snapshot_v3_record().source.model_dump(mode="json")
        | selected.source.model_dump(mode="json")
    )
    sources = tuple(
        replace(row, source=source)
        if row.source.item_revision_id == source.item_revision_id
        else row
        for row in value.capture.corpus.sources
    )
    corpus = replace(value.capture.corpus, sources=sources)
    value.capture = replace(value.capture, corpus=corpus)
    value.owner._sources.capture_in_session.return_value = value.capture
    if pin_visual:
        body = value.request.model_dump(mode="json")
        body["sources"][0]["source"] = source.model_dump(mode="json")
        value.request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    return source


@pytest.mark.parametrize("pin_visual", (False, True))
def test_reauthorized_visual_source_matches_core_report_without_dropping_visual_pin(
    admitted, pin_visual
):
    value = admitted
    source = _with_visual_admitted_source(value, pin_visual=pin_visual)
    assert value.owner.resolve_in_session(value.session, value.request) == value.inputs
    assert value.owner._sources.capture_in_session.return_value.corpus.sources[0].source is source


@pytest.mark.parametrize("fault", ("acceptance", "layout", "page", "missing_visual"))
def test_explicit_visual_pin_still_requires_exact_lineage(admitted, fault):
    value = admitted
    source = _with_visual_admitted_source(value, pin_visual=True)
    body = source.model_dump(mode="json")
    if fault == "acceptance":
        body["extraction_acceptance_sha256"] = "sha256:" + "0" * 64
    elif fault == "layout":
        body["layout_observation"]["observation_sha256"] = "sha256:" + "0" * 64
    elif fault == "page":
        body["page_inputs"][0]["image"]["sha256"] = "sha256:" + "0" * 64
    if fault == "missing_visual":
        changed = value.capture.entries[0].profile.source_basis.source
    else:
        changed = ApprovedPastExamItemKnowledgeSourceV3.model_validate(body)
    sources = tuple(
        replace(row, source=changed)
        if row.source.item_revision_id == source.item_revision_id
        else row
        for row in value.capture.corpus.sources
    )
    value.owner._sources.capture_in_session.return_value = replace(
        value.capture, corpus=replace(value.capture.corpus, sources=sources)
    )
    with pytest.raises(ValueError, match="SOURCE_PIN_MISMATCH"):
        value.owner.resolve_in_session(value.session, value.request)
    value.reader.read_member.assert_not_called()


@pytest.mark.parametrize(
    "fault", ("item", "revision", "artifact", "artifact_revision", "hash", "analysis_run")
)
def test_core_only_pin_rejects_different_authorized_member_or_analysis(admitted, fault):
    value = admitted
    source = _with_visual_admitted_source(value)
    body = source.model_dump(mode="json")
    if fault == "item":
        body["item_id"] = "item_" + "0" * 32
    elif fault == "revision":
        body["item_revision_id"] = "itemrev_" + "0" * 32
    elif fault == "artifact":
        body["artifact_member"]["artifact_id"] = "artifact_" + "0" * 32
    elif fault == "artifact_revision":
        body["artifact_member"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "hash":
        body["artifact_member"]["sha256"] = "sha256:" + "0" * 64
    changed = ApprovedPastExamItemKnowledgeSourceV3.model_validate(body)
    sources = tuple(
        replace(
            row,
            source=changed,
            analysis_run_id="analysisrun_" + "0" * 32
            if fault == "analysis_run"
            else row.analysis_run_id,
        )
        if row.source.item_revision_id == source.item_revision_id
        else row
        for row in value.capture.corpus.sources
    )
    value.owner._sources.capture_in_session.return_value = replace(
        value.capture, corpus=replace(value.capture.corpus, sources=sources)
    )
    with pytest.raises(ValueError, match="SOURCE_PIN_MISMATCH"):
        value.owner.resolve_in_session(value.session, value.request)
    value.reader.read_member.assert_not_called()


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
