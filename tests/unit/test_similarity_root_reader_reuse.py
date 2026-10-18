"""Real temporary immutable bytes, synthetic source/IAM; never a live latency claim."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import inference_transfer_population_read_set as read_set_module
from eom_catalog_service import pinned_artifact_resolution as pinned
from eom_catalog_service.embedding_registry_ports import ResolvedPinnedEmbeddingIndex
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_inference_transfer_candidate_admission import admission_scope
from tests.unit.test_pinned_artifact_read_context import MetadataSession
from tests.unit.test_pinned_artifact_resolution import _fixture
from tests.unit.test_similarity_context_service import CALLER, case


def population_read_set_case(monkeypatch):
    session = MetadataSession()
    session.in_nested_transaction = lambda: False
    session.new, session.dirty, session.deleted = set(), set(), set()
    reader = PinnedArtifactReadContext(session, pinned.CatalogSettings())
    scope = admission_scope(maximum=545)
    request, _sources, _query = case()
    recipe = request.views[0].recipe
    observation = read_set_module.InferenceTransferPopulationObservation(
        (
            read_set_module.InferenceTransferDependencyObservation(
                "fixture", 545, "sha256:" + "a" * 64
            ),
        )
    )
    observe = Mock(return_value=observation)
    monkeypatch.setattr(read_set_module, "observe_inference_transfer_population", observe)
    read_set = read_set_module.InferenceTransferPopulationReadSet(
        session,
        reader,
        operator_id=scope.requested_by,
        request_sha256=request.request_sha256,
    )
    capture = InferenceTransferSessionCapture(scope)
    return SimpleNamespace(
        session=session,
        reader=reader,
        scope=scope,
        recipe=recipe,
        request=request,
        read_set=read_set,
        capture=capture,
        observation=observation,
        observe=observe,
    )


def test_population_read_set_materializes_once_but_observes_before_after_and_three_later_fences(
    monkeypatch,
):
    value = population_read_set_case(monkeypatch)
    assert value.read_set.reuse(value.session, value.scope, value.recipe, value.reader) is None
    value.read_set.begin(value.session, value.scope, value.recipe, value.reader)
    # New numerical/query metadata in the same root is not source-membership drift.
    monkeypatch.setattr(value.reader, "provenance_identities", lambda: (("new", "newrev"),))
    value.read_set.complete(value.session, value.scope, value.recipe, value.reader, value.capture)
    for _phase in range(3):
        assert (
            value.read_set.reuse(value.session, value.scope, value.recipe, value.reader)
            is value.capture
        )
    assert value.observe.call_count == 5
    assert all(call.kwargs["artifact_identities"] == () for call in value.observe.call_args_list)
    with pytest.raises(FrozenInstanceError):
        value.capture.entries = ()


@pytest.mark.parametrize(
    "fault",
    [
        "session",
        "root",
        "inactive",
        "nested",
        "thread",
        "reader",
        "actor",
        "request",
        "scope",
        "recipe",
        "new",
        "dirty",
        "deleted",
    ],
)
def test_population_read_set_rejects_detached_or_changed_ownership_before_observation(
    monkeypatch, fault
):
    value = population_read_set_case(monkeypatch)
    value.read_set.begin(value.session, value.scope, value.recipe, value.reader)
    value.read_set.complete(value.session, value.scope, value.recipe, value.reader, value.capture)
    arguments = [value.session, value.scope, value.recipe, value.reader]
    if fault == "session":
        arguments[0] = MetadataSession()
    elif fault == "root":
        value.session.root = SimpleNamespace(is_active=True)
    elif fault == "inactive":
        value.session.root.is_active = False
    elif fault == "nested":
        value.session.in_nested_transaction = lambda: True
    elif fault == "thread":
        monkeypatch.setattr(read_set_module, "get_ident", lambda: -1)
    elif fault == "reader":
        arguments[3] = PinnedArtifactReadContext(value.session, value.reader.settings)
    elif fault == "scope":
        arguments[1] = replace(value.scope, maximum_candidates=546)
    elif fault == "recipe":
        arguments[2] = value.recipe.model_copy(update={"maximum_text_bytes": 1})
    elif fault in {"new", "dirty", "deleted"}:
        getattr(value.session, fault).add(object())
    count = value.observe.call_count
    with pytest.raises((InferenceTransferServiceError, pinned.PinnedArtifactResolutionError)):
        if fault in {"actor", "request"}:
            value.read_set.require_request(
                value.session,
                "operator_other" if fault == "actor" else value.scope.requested_by,
                "sha256:" + "0" * 64 if fault == "request" else value.request.request_sha256,
                value.reader,
            )
        else:
            value.read_set.reuse(*arguments)
    assert value.observe.call_count == count


@pytest.mark.parametrize(
    "phase", ["during_initial", "before_second", "before_third", "before_fourth"]
)
def test_population_read_set_rejects_initial_torn_capture_and_late_unranked_drift(
    monkeypatch, phase
):
    value = population_read_set_case(monkeypatch)
    value.read_set.begin(value.session, value.scope, value.recipe, value.reader)
    if phase != "during_initial":
        value.read_set.complete(
            value.session, value.scope, value.recipe, value.reader, value.capture
        )
        for _index in range({"before_second": 0, "before_third": 1, "before_fourth": 2}[phase]):
            assert (
                value.read_set.reuse(value.session, value.scope, value.recipe, value.reader)
                is value.capture
            )
    value.observe.return_value = read_set_module.InferenceTransferPopulationObservation(
        (replace(value.observation.groups[0], sha256="sha256:" + "b" * 64),)
    )
    with pytest.raises(InferenceTransferServiceError):
        if phase == "during_initial":
            value.read_set.complete(
                value.session, value.scope, value.recipe, value.reader, value.capture
            )
        else:
            value.read_set.reuse(value.session, value.scope, value.recipe, value.reader)


def test_population_read_set_cannot_replay_a_partial_failed_capture(monkeypatch):
    value = population_read_set_case(monkeypatch)
    value.read_set.begin(value.session, value.scope, value.recipe, value.reader)
    with pytest.raises(InferenceTransferServiceError):
        value.read_set.reuse(value.session, value.scope, value.recipe, value.reader)
    with pytest.raises(InferenceTransferServiceError):
        value.read_set.begin(value.session, value.scope, value.recipe, value.reader)


def test_real_snapshot_owner_materializes_545_distinct_entries_once_for_four_current_fences(
    monkeypatch,
):
    """Actual capture orchestration; source SQL/IAM are synthetic, not live latency."""
    from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
    from eom_catalog_service.inference_transfer_catalog_adapter import (
        AcceptedInferenceTransferProfileInput,
    )
    from eom_catalog_service.knowledge_retrieval_service import (
        KnowledgeRetrievalCandidate,
        ReadOnlyKnowledgeCandidatePool,
    )

    from tests.unit.inference_transfer_embedding_fixtures import embedding_entry
    from tests.unit.inference_transfer_fixtures import report
    from tests.unit.test_embedding_registry_catalog_adapter import _scope_owner

    snapshot, session, request, recipe, reader, fence, *_ = _scope_owner(monkeypatch)
    session.get_transaction.return_value.is_active = True
    session.in_nested_transaction.return_value = False
    session.new, session.dirty, session.deleted = set(), set(), set()
    reader.provenance_identities.return_value = ()
    observation = read_set_module.InferenceTransferPopulationObservation(())
    observe = Mock(return_value=observation)
    monkeypatch.setattr(read_set_module, "observe_inference_transfer_population", observe)
    entries = []
    for index in range(545):
        identity = f"{index:032x}"
        body = embedding_entry().model_dump(mode="json")
        body["profile"]["profile_id"] = "inferenceprofile_" + identity
        body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + identity
        basis = body["profile"]["source_basis"]
        basis["source"].update(item_id="item_" + identity, item_revision_id="itemrev_" + identity)
        pointer = basis["solution_evidence"]
        pointer["base_analysis_run_id"] = "analysisrun_" + identity
        pointer["pointer_sha256"] = content_sha256(
            {key: value for key, value in pointer.items() if key != "pointer_sha256"}
        )
        body["profile"]["profile_sha256"] = content_sha256(
            {key: value for key, value in body["profile"].items() if key != "profile_sha256"}
        )
        entries.append(StagedExperimentEntry.model_validate(body))
    pool = ReadOnlyKnowledgeCandidatePool(
        request.graph_snapshot,
        tuple(
            KnowledgeRetrievalCandidate(
                analysis_run_id=entry.profile.source_basis.solution_evidence.base_analysis_run_id,
                source=entry.profile.source_basis.source,
                node_ids=(),
                anchor_ids=(),
                node_labels=(),
                node_types=(),
                relevance_milli=0,
                answer_bearing=True,
            )
            for entry in entries
        ),
        False,
    )
    snapshot.sources.retrieval.admit_read_only_candidate_pool.return_value = pool
    snapshot.sources._resolve_profile_inputs.return_value = (
        tuple(AcceptedInferenceTransferProfileInput(entry.profile, report()) for entry in entries),
        0,
    )
    snapshot._materialize_entries.return_value = {
        entry.profile.source_basis.solution_evidence.base_analysis_run_id: entry
        for entry in entries
    }
    read_set = read_set_module.InferenceTransferPopulationReadSet(
        session,
        reader,
        operator_id=request.actor_id,
        request_sha256="sha256:" + "1" * 64,
    )
    values = [
        snapshot.capture_in_session(
            session,
            request,
            recipe,
            identity_fence=fence,
            artifact_reader=reader,
            population_read_set=read_set,
        )
        for _phase in range(4)
    ]
    assert all(value is values[0] for value in values)
    assert (
        len(values[0].entries)
        == len({entry.profile.source_basis.source.item_revision_id for entry in values[0].entries})
        == 545
    )
    assert observe.call_count == 5
    assert fence.fence_current_operator.call_count == 4
    assert snapshot.sources.retrieval._authorize.call_count == 4
    assert snapshot.sources.retrieval.resolve_snapshot_pointer.call_count == 4
    snapshot.sources.retrieval.admit_read_only_candidate_pool.assert_called_once()
    snapshot.sources._resolve_profile_inputs.assert_called_once()
    snapshot._materialize_entries.assert_called_once()


def test_first_capture_refreshes_lineage_after_baseline_before_admission(monkeypatch):
    """A stable new digest must never bless output from an older held ORM row."""
    from eom_catalog_service import inference_transfer_snapshot_catalog_adapter as module

    from tests.unit.test_embedding_registry_catalog_adapter import _scope_owner

    snapshot, session, request, recipe, reader, fence, *_ = _scope_owner(monkeypatch)
    session.get_transaction.return_value.is_active = True
    session.in_nested_transaction.return_value = False
    session.new, session.dirty, session.deleted = set(), set(), set()
    reader.provenance_identities.return_value = ()
    states = {"database": "ACCEPTED", "held": "ACCEPTED"}
    calls = []

    def prefetch(*_args):
        calls.append("prefetch")
        states["held"] = states["database"]
        return ()

    def observe(*_args, **_kwargs):
        calls.append("observe")
        states["database"] = "WITHDRAWN"
        return read_set_module.InferenceTransferPopulationObservation(())

    def admit(*_args, **_kwargs):
        assert states["held"] == "WITHDRAWN"
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH")

    monkeypatch.setattr(module, "prefetch_past_exam_artifact_closure", prefetch)
    monkeypatch.setattr(read_set_module, "observe_inference_transfer_population", observe)
    snapshot.sources.retrieval.admit_read_only_candidate_pool.side_effect = admit
    read_set = read_set_module.InferenceTransferPopulationReadSet(
        session,
        reader,
        operator_id=request.actor_id,
        request_sha256="sha256:" + "1" * 64,
    )
    with pytest.raises(InferenceTransferServiceError):
        snapshot.capture_in_session(
            session,
            request,
            recipe,
            identity_fence=fence,
            artifact_reader=reader,
            population_read_set=read_set,
        )
    assert calls == ["prefetch", "observe", "prefetch"]
    snapshot._materialize_entries.assert_not_called()


@pytest.mark.parametrize("fault", ("root", "settings", "thread", "registration"))
def test_borrowed_reader_is_not_an_authority_or_cross_root_handle(owner, monkeypatch, fault):
    from eom_catalog_service import embedding_registry_catalog_adapter as module

    verifier, session, command, *_ = owner
    request, _sources, _query = case()
    settings = verifier.settings
    if fault == "settings":
        settings = replace(settings, nas_artifact_root=settings.nas_artifact_root / "wrong")
    reader = PinnedArtifactReadContext(session, settings)
    if fault == "root":
        reader = PinnedArtifactReadContext(MetadataSession(), settings)
    elif fault == "thread":
        monkeypatch.setattr(pinned, "get_ident", lambda: -1)
    if fault == "registration":
        with pytest.raises(module.EmbeddingRegistryError):
            verifier._capture(
                session,
                CALLER,
                command,
                module.InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
                artifact_reader=reader,
            )
    else:
        with pytest.raises(SimilarityContextReadError):
            verifier.prepare_similarity_context_in_session(
                session, CALLER, request, artifact_reader=reader
            )
    verifier.sources.capture_in_session.assert_not_called()


@pytest.mark.parametrize("withdrawn", (False, True))
def test_real_catalog_reuses_one_reader_but_retains_four_fresh_population_captures(
    owner, monkeypatch, withdrawn
):
    from eom_catalog_service import embedding_registry_catalog_adapter as module

    verifier, session, command, _index, _binding, _scope, _root = owner
    request, _sources, _query = case()
    reader = PinnedArtifactReadContext(session, verifier.settings)
    original = verifier.sources.capture_in_session.side_effect
    phase_count = Counter()
    readers, hashes = [], []
    original_hash = pinned.sha256_file
    pointer = command.index_manifest

    def count_hash(path):
        hashes.append(path)
        return original_hash(path)

    def capture(actual_session, actual_command, recipe, **options):
        # Actual authority is intentionally synthetic here, but is called each time.
        current = original(actual_session, actual_command, recipe, **options)
        phase = options["phase"].value
        phase_count[phase] += 1
        context = options["artifact_reader"]
        readers.append(context)
        if phase == "CAPTURE_POPULATION":
            if withdrawn and phase_count[phase] == 4:
                old = session.records[(ArtifactRecord, pointer.artifact_id)]
                session.records[(ArtifactRecord, pointer.artifact_id)] = ArtifactRecord(
                    logical_artifact_id=old.logical_artifact_id,
                    job_id=old.job_id,
                    artifact_type=old.artifact_type,
                    approved=False,
                )
            context.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            context.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=1024 * 1024,
            )
        return current

    def index_read(actual_session, caller, intent, owner):
        owner.authorize_scope(actual_session, caller, intent.scope)
        owner._capture(
            actual_session,
            caller,
            intent.scope,
            module.InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
        )
        owner.authorize_scope(actual_session, caller, intent.scope)
        return ResolvedPinnedEmbeddingIndex(intent, (), (), (), ())

    monkeypatch.setattr(pinned, "sha256_file", count_hash)
    monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
    monkeypatch.setattr(module, "read_pinned_embedding_index", index_read)
    prepared = verifier.prepare_similarity_context_in_session(
        session, CALLER, request, artifact_reader=reader
    )
    verifier.read_similarity_views_in_session(
        session, CALLER, request, prepared, artifact_reader=reader
    )
    if withdrawn:
        with pytest.raises(SimilarityContextReadError):
            verifier.prepare_similarity_context_in_session(
                session, CALLER, request, artifact_reader=reader
            )
    else:
        assert (
            verifier.prepare_similarity_context_in_session(
                session, CALLER, request, artifact_reader=reader
            )
            == prepared
        )
    assert phase_count == {"CAPTURE_POPULATION": 4, "AUTHORIZE_SCOPE": 9}
    assert all(value is reader for value in readers)
    assert hashes == [
        Path(session.records[(ArtifactRevisionRecord, pointer.artifact_revision_id)].nas_path)
        / pointer.member_path
    ]


def test_completed_catalog_window_preserves_four_fences_nine_authorizations_and_one_capture(
    owner,
    monkeypatch,
):
    """Actual Catalog orchestration with synthetic source authority, not live SQL."""
    from eom_catalog_service import embedding_registry_catalog_adapter as module

    verifier, session, _command, _index, _binding, scope, _root = owner
    scope.requested_by = CALLER.operator_id
    request, _sources, _query = case()
    reader = PinnedArtifactReadContext(session, verifier.settings)
    read_set = verifier.create_similarity_population_read_set_in_session(
        session,
        CALLER,
        request,
        artifact_reader=reader,
    )
    observe = Mock(return_value=read_set_module.InferenceTransferPopulationObservation(()))
    monkeypatch.setattr(read_set_module, "observe_inference_transfer_population", observe)
    original = verifier.sources.capture_in_session.side_effect
    phases = Counter()
    materializations = []

    def capture(actual_session, command, recipe, **options):
        current = original(actual_session, command, recipe, **options)
        phases[options["phase"].value] += 1
        if options["phase"].value == "AUTHORIZE_SCOPE":
            return current
        assert options["population_read_set"] is read_set
        reused = read_set.reuse(actual_session, current.scope, recipe, reader)
        if reused is not None:
            return reused
        read_set.begin(actual_session, current.scope, recipe, reader)
        materializations.append(current)
        read_set.complete(actual_session, current.scope, recipe, reader, current)
        return current

    def index_read(actual_session, caller, intent, actual_owner):
        actual_owner.authorize_scope(actual_session, caller, intent.scope)
        actual_owner._capture(
            actual_session,
            caller,
            intent.scope,
            module.InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
        )
        actual_owner.authorize_scope(actual_session, caller, intent.scope)
        return ResolvedPinnedEmbeddingIndex(intent, (), (), (), ())

    monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
    monkeypatch.setattr(module, "read_pinned_embedding_index", index_read)
    prepared = verifier.prepare_similarity_context_in_session(
        session,
        CALLER,
        request,
        artifact_reader=reader,
        population_read_set=read_set,
    )
    verifier.read_similarity_views_in_session(
        session,
        CALLER,
        request,
        prepared,
        artifact_reader=reader,
        population_read_set=read_set,
    )
    assert (
        verifier.prepare_similarity_context_in_session(
            session,
            CALLER,
            request,
            artifact_reader=reader,
            population_read_set=read_set,
        )
        == prepared
    )
    assert phases == {"CAPTURE_POPULATION": 4, "AUTHORIZE_SCOPE": 9}
    assert len(materializations) == 1 and observe.call_count == 5


def test_520_member_four_phase_benchmark_reuses_bytes_not_current_authority(tmp_path, monkeypatch):
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, arguments["artifact_revision_id"])
    root = Path(revision.nas_path)
    revision.manifest["files"] = []
    descriptors = []
    for number in range(520):
        name = f"evidence/synthetic-{number}.json"
        payload = json.dumps({"value": number, "synthetic_padding": "x" * 4096}).encode()
        (root / name).write_bytes(payload)
        descriptor = {
            "file_name": name,
            "sha256": sha256_bytes(payload),
            "bytes": len(payload),
            "schema_ref": arguments["schema_ref"],
            "media_type": "application/json",
        }
        revision.manifest["files"].append(descriptor)
        descriptors.append(descriptor)
    # Preserve a valid canonical primary descriptor and bytes in addition to the520 rows.
    revision.manifest["files"].append(
        {
            "file_name": arguments["member_path"],
            "sha256": arguments["sha256"],
            "bytes": revision.content_bytes,
            "schema_ref": arguments["schema_ref"],
            "media_type": arguments["media_type"],
        }
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    hash_calls = []
    actual_hash = pinned.sha256_file
    monkeypatch.setattr(
        pinned, "sha256_file", lambda path: (hash_calls.append(path), actual_hash(path))[1]
    )
    results = {}
    for reuse in (False, True):
        session = MetadataSession(*original.records.values())
        shared = PinnedArtifactReadContext(session, settings) if reuse else None
        start, before = perf_counter(), len(hash_calls)
        totals = []
        for _phase in range(4):
            context = shared or PinnedArtifactReadContext(session, settings)
            context.prefetch(((arguments["artifact_id"], arguments["artifact_revision_id"]),))
            total = 0
            for descriptor in descriptors:
                total += len(
                    context.read_member(
                        artifact_id=arguments["artifact_id"],
                        revision_id=arguments["artifact_revision_id"],
                        member_path=descriptor["file_name"],
                        sha256=descriptor["sha256"],
                        schema_ref=descriptor["schema_ref"],
                        media_type="application/json",
                        max_bytes=8192,
                    )
                )
            totals.append(total)
        results["shared" if reuse else "independent"] = {
            "physical_reads": len(hash_calls) - before,
            "metadata_queries": len(session.statements),
            "elapsed_ms": round((perf_counter() - start) * 1000),
        }
        assert len(set(totals)) == 1 and totals[0] > 2 * 1024 * 1024
    assert results["independent"]["physical_reads"] == 2080
    assert results["shared"]["physical_reads"] == 520
    assert results["independent"]["metadata_queries"] == 12
    assert results["shared"]["metadata_queries"] == 3
    # No wall-time assertion: filesystem warmth/scheduling must not make correctness flaky.
    print(json.dumps({"synthetic_read_reuse_only_not_live_latency": results}, sort_keys=True))
