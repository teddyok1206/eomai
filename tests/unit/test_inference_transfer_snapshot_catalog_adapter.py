"""Synthetic Catalog owner reads; no DB/NAS/runtime/model access is exercised."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import eom_catalog_service.inference_transfer_snapshot_catalog_adapter as module
import pytest
from eom_catalog_contracts import EvidenceBudget
from eom_catalog_contracts.inference_transfer_experiment import CanonicalExperimentItemText
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    AcceptedInferenceTransferProfileInput,
    CatalogInferenceTransferSourceAdapter,
)
from eom_catalog_service.inference_transfer_item_projection import project_staged_item_entry
from eom_catalog_service.inference_transfer_projection import project_accepted_solution_report
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
)
from eom_catalog_service.inference_transfer_snapshot_service import (
    InferenceTransferSnapshotApplicationService,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalCandidate,
    KnowledgeRetrievalServiceError,
    ReadOnlyKnowledgeCandidatePool,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError

from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.inference_transfer_snapshot_fixtures import (
    snapshot_prepare,
    snapshot_read_request,
)
from tests.unit.test_inference_transfer_item_projection import (
    _accepted_report,
    _bound_profile,
    _item_v1,
)
from tests.unit.test_inference_transfer_snapshot_service import authorized_request


def owner_input(seed):
    item, report = _item_v1(), _accepted_report()
    body = _bound_profile(item, report).model_dump(mode="json", exclude={"profile_sha256"})
    body.update(
        profile_id="inferenceprofile_" + seed * 32,
        profile_revision_id="inferenceprofilerev_" + seed * 32,
    )
    source = body["source_basis"]["source"]
    source.update(item_id="item_" + seed * 32, item_revision_id="itemrev_" + seed * 32)
    source["artifact_member"].update(
        artifact_id="artifact_" + seed * 32, artifact_revision_id="rev_" + seed * 32
    )
    pointer = body["source_basis"]["solution_evidence"]
    pointer["base_analysis_run_id"] = "analysisrun_" + seed * 32
    pointer.pop("pointer_sha256")
    pointer["pointer_sha256"] = content_sha256(pointer)
    profile = InferenceTransferProfile.model_validate(
        body | {"profile_sha256": content_sha256(body)}
    )
    profile = project_accepted_solution_report(
        source_basis=profile.source_basis,
        report=report,
        created_at=NOW,
    )
    candidate = KnowledgeRetrievalCandidate(
        analysis_run_id=pointer["base_analysis_run_id"],
        source=profile.source_basis.source,
        node_ids=(),
        anchor_ids=(),
        node_labels=(),
        node_types=(),
        relevance_milli=800,
        answer_bearing=True,
    )
    return (
        AcceptedInferenceTransferProfileInput(profile, report),
        candidate,
        canonical_json_bytes(item),
    )


@pytest.fixture
def owner(monkeypatch):
    rows = tuple(owner_input(seed) for seed in "abc")
    adapter = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    adapter.engine = Mock()
    adapter.sources = object.__new__(CatalogInferenceTransferSourceAdapter)
    adapter.sources.retrieval = Mock()

    def fresh_context(_session: object, _scope: object) -> object:
        return object()

    adapter.sources.retrieval.create_read_only_reuse_context.side_effect = fresh_context
    session, context = MagicMock(), MagicMock()
    context.__enter__.return_value = session
    adapter.sources.sessions = Mock(return_value=context)
    scope = SimpleNamespace(
        evidence_budget=EvidenceBudget(
            max_documents=8,
            max_item_revisions=8,
            max_graph_nodes=256,
            max_claims=32,
            max_context_tokens=8000,
        ),
        access_policy_revision_id=snapshot_prepare().access_policy_revision_id,
        requester_role="EDITOR",
        requester_permission_keys=("knowledge_graph:retrieve",),
        requested_by="real-test-operator",
    )
    monkeypatch.setattr(adapter.sources, "_scope", Mock(return_value=scope))
    pool = ReadOnlyKnowledgeCandidatePool(
        snapshot_prepare().graph_snapshot, tuple(row[1] for row in rows), False
    )
    adapter.sources.retrieval.admit_read_only_candidate_pool.return_value = pool
    monkeypatch.setattr(
        adapter.sources,
        "_resolve_profile_inputs",
        Mock(return_value=(tuple(row[0] for row in rows), 0)),
    )
    adapter.sources.retrieval.topic_keys_for_terms.return_value = ("concept:motion",)
    adapter.sources.retrieval.retrieve_read_only.return_value = SimpleNamespace(
        candidates=(rows[2][1], rows[0][1], rows[1][1], rows[1][1])
    )
    payloads = {
        row[0].profile.source_basis.source.artifact_member.artifact_id: row[2] for row in rows
    }
    reader = Mock(
        side_effect=lambda _engine, reads: tuple(
            payloads[read.pointer.artifact_id] for read in reads
        )
    )
    monkeypatch.setattr(module, "resolve_control_artifact_members", reader)
    return SimpleNamespace(
        adapter=adapter,
        rows=rows,
        scope=scope,
        pool=pool,
        reader=reader,
        session=session,
        payloads=payloads,
    )


def test_prepare_uses_actual_actor_occurrence_scope_without_reading_original_item_bytes(owner):
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    result = service.prepare("real-test-operator", snapshot_prepare(query_item_revision_ids=()))
    command = owner.adapter.sources._scope.call_args.args[1]
    assert command.actor_id == "real-test-operator"
    assert command.population_scope.value == "OCCURRENCE_BACKED_PAST_EXAM"
    assert not hasattr(command, "query_item_revision_id")
    assert result.header.source_count == 3
    owner.reader.assert_not_called()
    owner.adapter.sources.retrieval.retrieve_read_only.assert_not_called()
    assert "READ ONLY" in str(owner.session.execute.call_args.args[0])


def test_read_only_selected_bytes_but_admits_whole_population_first(owner):
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", snapshot_prepare())
    result = service.read(
        "real-test-operator",
        snapshot_read_request(prepared, selected_index_entries=prepared.index[:1]),
    )
    assert owner.adapter.sources.retrieval.admit_read_only_candidate_pool.call_count == 2
    assert len(owner.reader.call_args.args[1]) == 1
    assert len(result.records) == 1
    text = result.records[0].staged_entry.content.text
    assert "속력은 -36 km/h" in text and "SOLUTION_ONLY" not in text
    assert "TITLE_INTERNAL_ONLY" not in text
    assert tuple(
        row.profile_revision_id for row in result.baselines[0].ordered_candidates
    ) == tuple(owner.rows[i][0].profile.profile_revision_id for i in (2, 1))
    command = owner.adapter.sources.retrieval.retrieve_read_only.call_args.args[1]
    assert command.target_item_revision_id is None
    assert command.requested_by == "real-test-operator"
    assert command.requester_role == "EDITOR"
    assert command.evidence_budget == owner.scope.evidence_budget


def test_capture_shares_only_one_public_reuse_context_and_next_read_starts_fresh(
    owner: SimpleNamespace,
) -> None:
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    request = snapshot_prepare(
        query_item_revision_ids=tuple(
            sorted(row[0].profile.source_basis.source.item_revision_id for row in owner.rows)
        )
    )
    prepared = service.prepare("real-test-operator", request)
    read = snapshot_read_request(prepared, selected_index_entries=prepared.index)
    first = service.read("real-test-operator", read)
    second = service.read("real-test-operator", read)
    retrieval = owner.adapter.sources.retrieval

    assert retrieval.create_read_only_reuse_context.call_count == 3
    pool_contexts = tuple(
        call.kwargs["reuse_context"]
        for call in retrieval.admit_read_only_candidate_pool.call_args_list
    )
    assert len({id(value) for value in pool_contexts}) == 3
    assert retrieval.retrieve_read_only.call_count == 6
    assert all(
        call.kwargs["reuse_context"] is pool_contexts[1]
        for call in retrieval.retrieve_read_only.call_args_list[:3]
    )
    assert all(
        call.kwargs["reuse_context"] is pool_contexts[2]
        for call in retrieval.retrieve_read_only.call_args_list[3:]
    )
    assert all(
        call.args == (owner.session, owner.scope)
        for call in retrieval.create_read_only_reuse_context.call_args_list
    )
    assert first == second


@pytest.mark.parametrize("population_size", (64, 65, 67))
def test_official_baseline_prefix_is_explicit_and_preserves_population(
    owner: SimpleNamespace, population_size: int
) -> None:
    """Reproduce the producer/consumer bound mismatch without a live Catalog.

    Official read-only retrieval can return 256 raw candidates before authoring
    materialization applies its policy budget. The frozen baseline permits 64.
    A 67-source fixture formerly escaped with SuppliedGraphBaseline/too_long.
    The bounded projection retains the official prefix with an explicit limit;
    neither source membership nor the official retrieval algorithm is changed.
    """
    rows = []
    for index in range(1, population_size + 1):
        original, candidate, payload = owner_input("a")
        body = original.profile.model_dump(mode="json", exclude={"profile_sha256"})
        identity = f"{index:032x}"
        source = body["source_basis"]["source"]
        source.update(item_id="item_" + identity, item_revision_id="itemrev_" + identity)
        source["artifact_member"].update(
            artifact_id="artifact_" + identity, artifact_revision_id="rev_" + identity
        )
        solution = body["source_basis"]["solution_evidence"]
        solution["base_analysis_run_id"] = "analysisrun_" + identity
        solution.pop("pointer_sha256")
        solution["pointer_sha256"] = content_sha256(solution)
        profile = InferenceTransferProfile.model_validate(
            body | {"profile_sha256": content_sha256(body)}
        )
        profile = project_accepted_solution_report(
            source_basis=profile.source_basis,
            report=original.report,
            created_at=NOW,
        )
        rows.append(
            (
                AcceptedInferenceTransferProfileInput(profile, original.report),
                replace(
                    candidate,
                    analysis_run_id=solution["base_analysis_run_id"],
                    source=profile.source_basis.source,
                ),
                payload,
            )
        )
    candidates = tuple(row[1] for row in rows)
    owner.adapter.sources.retrieval.admit_read_only_candidate_pool.return_value = replace(
        owner.pool, candidates=candidates
    )
    owner.adapter.sources._resolve_profile_inputs.return_value = (
        tuple(row[0] for row in rows),
        0,
    )
    owner.adapter.sources.retrieval.retrieve_read_only.return_value = SimpleNamespace(
        candidates=tuple(reversed(candidates))
    )
    owner.payloads.update(
        {row[0].profile.source_basis.source.artifact_member.artifact_id: row[2] for row in rows}
    )
    request = snapshot_prepare(
        query_item_revision_ids=(rows[0][0].profile.source_basis.source.item_revision_id,)
    )
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", request)
    assert prepared.header.source_count == population_size
    assert len(prepared.index) == population_size
    result = service.read(
        "real-test-operator",
        snapshot_read_request(prepared, selected_index_entries=prepared.index[:1]),
    )
    baseline = result.baselines[0]
    full_order = tuple(
        InferenceTransferProfilePointer.from_profile(row[0].profile) for row in reversed(rows[1:])
    )
    assert baseline.ordered_candidates == full_order[:64]
    bounded_limitation = (
        "Official read-only Graph candidate order has 66 eligible comparisons; "
        "this bounded baseline retains the first 64 in unchanged order. "
        "Remaining candidates are not recorded in this baseline; it is not the "
        "final authoring Evidence selection."
    )
    if len(full_order) <= 64:
        original_body = baseline.model_dump(mode="json", exclude={"result_sha256"})
        original_body["ordered_candidates"] = [
            pointer.model_dump(mode="json") for pointer in full_order
        ]
        assert baseline.result_sha256 == content_sha256(original_body)
        assert not any("bounded baseline retains" in text for text in result.limitations)
    else:
        assert bounded_limitation in result.limitations
    assert len(owner.reader.call_args.args[1]) == 1
    assert (
        len(owner.adapter.sources.retrieval.retrieve_read_only.return_value.candidates)
        == population_size
    )


def test_current_permission_failure_precedes_any_bytes(owner):
    owner.adapter.sources._scope.side_effect = InferenceTransferServiceError(
        "INFERENCE_TRANSFER_FORBIDDEN"
    )
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        owner.adapter.capture("real-test-operator", snapshot_prepare())
    owner.reader.assert_not_called()
    owner.adapter.sources.retrieval.admit_read_only_candidate_pool.assert_not_called()


def test_population_drift_precedes_selected_bytes(owner):
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", snapshot_prepare())
    owner.adapter.sources.retrieval.admit_read_only_candidate_pool.return_value = replace(
        owner.pool, candidates=owner.pool.candidates[:2]
    )
    owner.adapter.sources._resolve_profile_inputs.return_value = (
        tuple(row[0] for row in owner.rows[:2]),
        0,
    )
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        service.read(
            "real-test-operator",
            snapshot_read_request(prepared, selected_index_entries=prepared.index[:1]),
        )
    owner.reader.assert_not_called()


def test_missing_report_source_remains_in_population_and_query_unavailable(owner):
    owner.adapter.sources._resolve_profile_inputs.return_value = (
        tuple(row[0] for row in owner.rows[1:]),
        1,
    )
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", snapshot_prepare())
    result = service.read(
        "real-test-operator",
        snapshot_read_request(prepared, selected_index_entries=prepared.index[:1]),
    )
    assert prepared.header.missing_report_count == 1 and prepared.header.source_count == 3
    assert result.records[0].staged_entry is None
    assert result.baselines == () and result.limitations
    owner.reader.assert_not_called()


def test_official_baseline_rejects_same_item_with_other_exact_source_or_run(owner):
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", snapshot_prepare())
    wrong_source = owner.rows[1][1].source.model_copy(
        update={"item_revision_id": "itemrev_" + "f" * 32}
    )
    candidate = replace(owner.rows[1][1], source=wrong_source)
    owner.adapter.sources.retrieval.retrieve_read_only.return_value = SimpleNamespace(
        candidates=(candidate,)
    )
    result = service.read(
        "real-test-operator",
        snapshot_read_request(prepared, selected_index_entries=prepared.index[:1]),
    )
    assert result.baselines[0].ordered_candidates == () and result.limitations


def test_lexical_seed_cap_is_explicit_and_does_not_truncate_question_tail(owner):
    supplied = owner.rows[0][0]
    entry = project_staged_item_entry(
        profile=supplied.profile,
        item=_item_v1(),
        accepted_report=supplied.report,
        recipe=snapshot_prepare().recipe,
    )
    assert entry.content is not None
    text = entry.content.text + " " + " ".join(f"token{i:03}" for i in range(140))
    text += " 12 kg이며 질량은 감소하지 않는다."
    content = CanonicalExperimentItemText(
        text=text,
        original_source=entry.content.original_source,
        text_sha256=content_sha256(text),
    )
    entry = entry.model_copy(update={"content": content})
    sources = tuple(
        module.AdmittedInferenceTransferSource(row[1].analysis_run_id, row[1].source)
        for row in owner.rows
    )
    _, limitations = owner.adapter._baselines(
        owner.session,
        snapshot_prepare(),
        owner.scope,
        {supplied.profile.source_basis.solution_evidence.base_analysis_run_id: entry},
        tuple(row[0] for row in owner.rows),
        sources,
        reuse_context=owner.adapter.sources.retrieval.create_read_only_reuse_context(
            owner.session, owner.scope
        ),
    )
    terms = owner.adapter.sources.retrieval.topic_keys_for_terms.call_args.kwargs["terms"]
    assert len(terms) == 128 and terms == tuple(sorted(set(terms)))
    assert any("128" in value for value in limitations)
    assert entry.content.text.endswith("12 kg이며 질량은 감소하지 않는다.")


def test_authorize_nonselected_source_drift_is_rejected_before_reading_all_bytes(owner):
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", snapshot_prepare())
    read = service.read("real-test-operator", snapshot_read_request(prepared))
    owner.reader.reset_mock()
    owner.adapter.sources.retrieval.admit_read_only_candidate_pool.return_value = replace(
        owner.pool,
        candidates=owner.pool.candidates[:2],
    )
    owner.adapter.sources._resolve_profile_inputs.return_value = (
        tuple(row[0] for row in owner.rows[:2]),
        0,
    )
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        service.authorize("real-test-operator", authorized_request(prepared, read))
    owner.reader.assert_not_called()


@pytest.mark.parametrize("case", ["no_topics", "insufficient", "empty_result"])
def test_unmaterialized_baseline_is_distinct_from_materialized_empty(owner, case):
    service = InferenceTransferSnapshotApplicationService(owner.adapter)
    prepared = service.prepare("real-test-operator", snapshot_prepare())
    if case == "no_topics":
        owner.adapter.sources.retrieval.topic_keys_for_terms.return_value = ()
    elif case == "insufficient":
        owner.adapter.sources.retrieval.retrieve_read_only.side_effect = (
            KnowledgeRetrievalServiceError("KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE", "synthetic")
        )
    else:
        owner.adapter.sources.retrieval.retrieve_read_only.return_value = SimpleNamespace(
            candidates=()
        )
    result = service.read(
        "real-test-operator",
        snapshot_read_request(prepared, selected_index_entries=prepared.index[:1]),
    )
    assert result.limitations
    assert len(result.baselines) == (1 if case == "empty_result" else 0)


@pytest.mark.parametrize(
    "case", ["size", "hash_failure", "invalid_json", "duplicate_json_key", "nonfinite_json"]
)
def test_invalid_original_bytes_fail_not_silently_unavailable(owner, case):
    if case == "hash_failure":
        owner.reader.side_effect = ControlArtifactResolutionError("CONTROL_ARTIFACT_HASH_MISMATCH")
    else:
        raw = owner.rows[0][2]
        if case == "size":
            raw = raw[:-1]
        elif case == "invalid_json":
            raw = b"x" * len(raw)
        elif case == "duplicate_json_key":
            raw = b'{"x":1,"x":2}' + b" " * (len(raw) - 13)
        else:
            raw = b'{"x":NaN}' + b" " * (len(raw) - 9)
        owner.payloads[owner.rows[0][0].profile.source_basis.source.artifact_member.artifact_id] = (
            raw
        )
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        owner.adapter._materialize_entries(snapshot_prepare(), (owner.rows[0][0],))


def test_supported_schema_hash_pointer_is_forwarded_exactly_to_owner_reader(owner):
    owner.adapter._materialize_entries(snapshot_prepare(), (owner.rows[0][0],))
    read = owner.reader.call_args.args[1][0]
    member = owner.rows[0][0].profile.source_basis.source.artifact_member
    assert read.pointer.artifact_id == member.artifact_id
    assert read.pointer.artifact_revision_id == member.artifact_revision_id
    assert read.pointer.sha256 == member.sha256 and read.pointer.schema_ref == member.schema_ref
    assert read.maximum_bytes == member.bytes


def test_batches_project_before_next_read_and_never_keep_all_raw_payloads(owner, monkeypatch):
    events = []
    original_project = module.project_staged_item_entry
    original_reader = owner.reader.side_effect

    def reader(engine, reads):
        events.append("read")
        return original_reader(engine, reads)

    def projector(**kwargs):
        events.append("project")
        return original_project(**kwargs)

    monkeypatch.setattr(
        module,
        "_MAXIMUM_ARTIFACT_BATCH_BYTES",
        owner.rows[0][0].profile.source_basis.source.artifact_member.bytes,
    )
    monkeypatch.setattr(module, "project_staged_item_entry", projector)
    owner.reader.side_effect = reader
    result = owner.adapter._materialize_entries(
        snapshot_prepare(), tuple(row[0] for row in owner.rows)
    )
    assert len(result) == 3
    assert events == ["read", "project", "read", "project", "read", "project"]


def test_shared_pointer_reads_and_parses_once_but_keeps_two_profile_identities(owner, monkeypatch):
    left, right = owner.rows[0][0], owner.rows[1][0]
    body = right.profile.model_dump(mode="json", exclude={"profile_sha256"})
    body["source_basis"]["source"]["artifact_member"] = (
        left.profile.source_basis.source.artifact_member.model_dump(mode="json")
    )
    right = replace(
        right,
        profile=InferenceTransferProfile.model_validate(
            body | {"profile_sha256": content_sha256(body)}
        ),
    )
    parser = Mock(wraps=module.read_item_content)
    monkeypatch.setattr(module, "read_item_content", parser)
    result = owner.adapter._materialize_entries(snapshot_prepare(), (left, right))
    assert len(owner.reader.call_args.args[1]) == 1 and parser.call_count == 1
    assert {value.profile.profile_id for value in result.values()} == {
        left.profile.profile_id,
        right.profile.profile_id,
    }


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("schema_ref", "eom://schemas/unsupported/1.0", "SCHEMA_UNAVAILABLE"),
        ("media_type", "text/plain", "MEDIA_TYPE_UNAVAILABLE"),
        ("bytes", 20 * 1024**2, "BYTES_TOO_LARGE"),
    ],
)
def test_unsupported_views_are_wholly_unavailable_without_fallback_read(owner, field, value, code):
    supplied = owner.rows[0][0]
    body = supplied.profile.model_dump(mode="json", exclude={"profile_sha256"})
    body["source_basis"]["source"]["artifact_member"][field] = value
    profile = InferenceTransferProfile.model_validate(
        body | {"profile_sha256": content_sha256(body)}
    )
    result = owner.adapter._materialize_entries(
        snapshot_prepare(), (replace(supplied, profile=profile),)
    )
    entry = next(iter(result.values()))
    assert entry.content is None and entry.metadata == ()
    assert code in entry.limitations[0]
    owner.reader.assert_not_called()
