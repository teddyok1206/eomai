"""Real local index3/numeric1 file reads; source/IAM and ledger ports are synthetic."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    RESULT_SCHEMA_REF,
    EmbeddingVectorShardManifest,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_application import read_pinned_embedding_index
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    RegisteredEmbeddingIndexRead,
)
from eom_catalog_service.embedding_registry_repository import binding_columns
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_source_capture import CatalogPublicSolutionSourceCapture
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_input,
    embedding_result,
    seal,
    shard_pointer,
)
from tests.unit.test_embedding_registry_catalog_adapter import OwnerSession, _file_set
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_public_solution_index_assembly import assemble, setup
from tests.unit.test_public_solution_similarity_contracts import member
from tests.unit.test_public_solution_similarity_service import composition_case


@pytest.fixture
def public_read(owner, tmp_path, monkeypatch):
    old, _, command, _, _, scope, _ = owner
    request, captured, old_document, _ = composition_case()
    data = setup()
    entries, available, ((_, original_shard),), namespace, space = data
    binary = pack_unit_vectors(
        (old_document.numerical_rows[0].values,), dimension=space.model_spec.dimension
    )
    body = original_shard.model_dump(mode="json")
    body["binary"]["sha256"] = sha256_bytes(binary)
    shard = EmbeddingVectorShardManifest.model_validate(seal(body, "shard_sha256"))
    shard_member = shard_pointer(shard)
    rows = tuple(
        RegisteredEmbeddingRow(
            row.encoding, row.row_ref.model_copy(update={"shard_manifest": shard_member})
        )
        for row in available
    )
    index = assemble((entries, rows, ((shard_member, shard),), namespace, space)).index
    index_member = member(
        index,
        schema="eom://schemas/knowledge/embedding-index-manifest/3.0",
        name="index.json",
        seed="b",
    )
    selection = request.views[0].model_copy(
        update={
            "index": request.views[0].index.model_copy(
                update={
                    "index_manifest": index_member,
                    "index_sha256": index.index_sha256,
                }
            )
        }
    )
    intent = replace(old_document.intent, selection=selection)
    native = embedding_input(
        entries[0].public_solution.text, space=space, storage_partition=namespace.storage_partition
    )
    result = embedding_result(native, shard=shard)
    root = tmp_path / "public"
    records = (
        *_file_set(
            root,
            shard_member.artifact_id,
            shard_member.artifact_revision_id,
            "control_incremental_embedding",
            "result.json",
            {
                "result.json": (
                    canonical_json_bytes(result.model_dump(mode="json")),
                    RESULT_SCHEMA_REF,
                    "application/json",
                ),
                "shard.json": (
                    canonical_json_bytes(shard.model_dump(mode="json")),
                    shard_member.schema_ref,
                    "application/json",
                ),
                "vectors.f32": (binary, shard.binary.schema_ref, "application/octet-stream"),
            },
            "c",
        ),
        *_file_set(
            root,
            index_member.artifact_id,
            index_member.artifact_revision_id,
            "control_embedding_index",
            "index.json",
            {
                "index.json": (
                    canonical_json_bytes(index.model_dump(mode="json")),
                    index_member.schema_ref,
                    "application/json",
                ),
            },
            "d",
        ),
    )
    session = OwnerSession(command, *records)
    session.in_transaction = lambda: session.root.is_active
    session.get_bind = lambda: old.engine
    verifier = CatalogEmbeddingRegistryVerifier(
        old.engine,
        replace(
            old.configuration,
            corpus_id=captured.corpus_id,
            namespace=namespace,
            space=space,
            recipe=entries[0].recipe,
            source_classes=("APPROVED_ITEM", "PAST_EXAM"),
        ),
        identity_fence=old.identity_fence,
        settings=CatalogSettings(nas_artifact_root=root),
    )
    corpus = AdmittedInferenceTransferCorpus(
        (),
        (),
        False,
        0,
        tuple(
            AdmittedInferenceTransferSource(entry.base_analysis_run_id, entry.source)
            for entry in entries
        ),
    )

    def authorize(session, supplied, **options):
        options["artifact_reader"].require_session(session)
        options["identity_fence"].fence_current_operator(session, supplied.actor_id)
        return scope

    def capture(_self, session, supplied, recipe, **options):
        authorize(
            session,
            supplied,
            **{key: options[key] for key in ("artifact_reader", "identity_fence")},
        )
        assert recipe == entries[0].recipe
        return CapturedPublicSolutionSources(
            entries, (), tuple(entry.source.item_revision_id for entry in entries), scope, corpus
        )

    verifier.sources.authorize_scope_in_session = Mock(side_effect=authorize)
    monkeypatch.setattr(
        CatalogPublicSolutionSourceCapture, "capture_population_in_session", capture
    )

    def selected_capture(_self, session, supplied, recipe, **options):
        observed = capture(_self, session, supplied, recipe, **options)
        keys = set(supplied.source_revision_ids)
        selected_entries = tuple(
            entry for entry in observed.entries if entry.source.item_revision_id in keys
        )
        selected_corpus = replace(
            corpus,
            sources=tuple(row for row in corpus.sources if row.source.item_revision_id in keys),
        )
        return replace(
            observed,
            entries=selected_entries,
            source_revision_ids=tuple(sorted(keys)),
            corpus=selected_corpus,
        )

    monkeypatch.setattr(CatalogPublicSolutionSourceCapture, "capture_in_session", selected_capture)
    registered = RegisteredEmbeddingIndexRead(
        captured.corpus_id,
        namespace,
        index.index_id,
        index.index_revision_id,
        index_member,
        index.index_sha256,
        request.graph_snapshot.graph_snapshot_revision_id,
        request.policy_revision_id,
        request.policy_sha256,
        len(index.bindings),
        content_sha256([binding.binding_sha256 for binding in index.bindings]),
    )
    ledger = {
        binding.binding_sha256: EmbeddingSourceBindingRecord(
            **binding_columns(binding),
            **{
                "binding_manifest_" + name: field
                for name, field in index_member.model_dump(mode="python").items()
            },
        )
        for binding in index.bindings
    }
    encoded = {
        row.encoding.encoding_sha256: EmbeddingEncodingRecord(
            **row.encoding.model_dump(mode="python"),
            **{
                "shard_" + name: field
                for name, field in shard_member.model_dump(mode="python").items()
            },
            row_index=row.row_ref.row_index,
        )
        for row in rows
    }
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_application.EmbeddingRegistryRepository.read_pinned_revision",
        lambda *args: registered,
    )
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_repository.EmbeddingRegistryRepository.current_namespace_revision",
        lambda *args: (registered, 2),
    )
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_application.EmbeddingRegistryRepository.bindings",
        lambda *args: ledger,
    )
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_application.EmbeddingRegistryRepository.encodings",
        lambda *args: encoded,
    )
    return SimpleNamespace(
        verifier=verifier,
        session=session,
        intent=intent,
        root=root,
        shard=shard_member,
        index=index,
        index_member=index_member,
        entries=entries,
        original_request=request,
    )


def invoke(value):
    return read_pinned_embedding_index(
        value.session, EmbeddingRegistryCaller("operator_" + "1" * 32), value.intent, value.verifier
    )


def test_actual_public_index_and_shared_numeric_row_keep_distinct_source_proofs(public_read):
    observed = invoke(public_read)
    assert observed.available_binding_count == 2 and len(observed.numerical_rows) == 1
    assert {binding.evidence.kind for binding in observed.bindings} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
    }
    assert all(
        profile.profile.schema_ref == "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
        for profile in observed.profiles
    )
    assert observed.bindings[0].encoding == observed.bindings[1].encoding
    assert observed.bindings[0].source != observed.bindings[1].source


@pytest.mark.parametrize("fault", ["tamper", "revoked", "report", "base"])
def test_public_read_keeps_file_report_and_lifecycle_validation(public_read, fault, monkeypatch):
    value = public_read
    if fault == "tamper":
        (
            value.root / value.shard.artifact_id / value.shard.artifact_revision_id / "vectors.f32"
        ).write_bytes(b"bad")
    elif fault == "revoked":
        value.session.get(ArtifactRecord, value.shard.artifact_id).approved = False
    else:
        from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry

        body = value.entries[0].model_dump(mode="json")
        if fault == "base":
            body["base_analysis_run_id"] = "analysisrun_" + "f" * 32
            if body["evidence"]["kind"] == "ACCEPTED_SOLUTION_ANALYSIS":
                body["evidence"]["solution"]["base_analysis_run_id"] = body["base_analysis_run_id"]
        else:
            body["policy_sha256"] = "sha256:" + "f" * 64
        altered = PublicSolutionEmbeddingEntry.model_validate(seal(body, "entry_sha256"))
        original = value.verifier._captured_lookup

        def changed(*args):
            current = original(*args)
            return replace(current, entries=(altered, *current.entries[1:]))

        monkeypatch.setattr(value.verifier, "_captured_lookup", changed)
    with pytest.raises(EmbeddingRegistryError):
        invoke(value)


def test_official_public_read_prepares_pinned_request_and_recaptures_exact_sources(public_read):
    from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
    from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
    from eom_catalog_service.embedding_registry_ports import SelectedEmbeddingSources
    from eom_catalog_service.public_solution_similarity_read import (
        CatalogPublicSolutionSimilarityRead,
        PublicSolutionSimilarityPreparation,
    )

    from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
    from tests.unit.test_public_solution_similarity_service import composition_case

    value = public_read
    application = CatalogPublicSolutionSimilarityRead(value.verifier)
    anchor = value.original_request.anchor
    preparation = PublicSolutionSimilarityPreparation(
        "similarityrequest_" + "2" * 32,
        SelectedEmbeddingSources(value.intent.scope, (anchor.source.item_revision_id,)),
        value.intent.selection.index.spaces,
        "ITEM_DATABASE_SEARCH",
        5,
    )
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    request = application.prepare_in_session(value.session, caller, preparation)
    assert request.anchor == anchor
    assert request.views[0].index.index_manifest == value.index_member
    _, _, _, original_query = composition_case()
    numerical = PublicSolutionQueryInput.model_validate(
        seal(
            original_query.request.model_dump(mode="json")
            | {"context_request_sha256": request.request_sha256},
            "request_sha256",
        )
    )
    backend = SyntheticNativeBackend(numerical.spaces.query)
    backend.batch_size, backend.threads = numerical.batch_size, numerical.threads
    encoded = encode_public_solution_query(numerical, backend)
    query = replace(
        original_query,
        request=numerical,
        result=encoded.result,
        binary=encoded.vectors,
        result_member=member(
            encoded.result, schema=original_query.result_member.schema_ref, name="result.json"
        ),
        shard_member=member(
            encoded.result.shard, schema=original_query.shard_member.schema_ref, name="shard.json"
        ),
    )
    result = application.read_in_session(value.session, caller, request, query)
    assert result.status == "READY" and len(result.candidates) == 1
    assert result.request == request
    assert value.verifier.sources.authorize_scope_in_session.call_count >= 4


def test_public_read_replay_never_resolves_latest_index(public_read, monkeypatch):
    from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
    from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityRequest
    from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
    from eom_catalog_service.public_solution_similarity_read import (
        CatalogPublicSolutionSimilarityRead,
    )

    from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
    from tests.unit.test_public_solution_similarity_service import composition_case

    value = public_read
    request = PublicSolutionSimilarityRequest.model_validate(
        seal(
            value.original_request.model_dump(mode="json")
            | {"views": [value.intent.selection.model_dump(mode="json")]},
            "request_sha256",
        )
    )
    _, _, _, query = composition_case()
    numerical = PublicSolutionQueryInput.model_validate(
        seal(
            query.request.model_dump(mode="json")
            | {"context_request_sha256": request.request_sha256},
            "request_sha256",
        )
    )
    backend = SyntheticNativeBackend(numerical.spaces.query)
    backend.batch_size, backend.threads = numerical.batch_size, numerical.threads
    output = encode_public_solution_query(numerical, backend)
    query = replace(
        query,
        request=numerical,
        result=output.result,
        binary=output.vectors,
        result_member=member(
            output.result, schema=query.result_member.schema_ref, name="result.json"
        ),
        shard_member=member(
            output.result.shard, schema=query.shard_member.schema_ref, name="shard.json"
        ),
    )
    latest = Mock(side_effect=AssertionError("historical read must not select current head"))
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_repository.EmbeddingRegistryRepository.current_namespace_revision",
        latest,
    )
    application = CatalogPublicSolutionSimilarityRead(value.verifier)
    prepared = application.prepare_query_in_session(
        value.session, EmbeddingRegistryCaller("operator_" + "1" * 32), request
    )
    assert prepared.request_sha256 == request.request_sha256
    assert prepared.anchor == request.anchor and prepared.row == numerical.rows[0]
    result = application.read_in_session(
        value.session, EmbeddingRegistryCaller("operator_" + "1" * 32), request, query
    )
    assert result.request.views[0].index.index_manifest == value.index_member
    latest.assert_not_called()


def test_public_query_source_preparation_reauthorizes_after_text_materialization(
    public_read, monkeypatch
):
    from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityRequest
    from eom_catalog_service.public_solution_similarity_read import (
        CatalogPublicSolutionSimilarityRead,
    )
    from eom_catalog_service.similarity_context_ports import SimilarityContextReadError

    value = public_read
    request = PublicSolutionSimilarityRequest.model_validate(
        seal(
            value.original_request.model_dump(mode="json")
            | {"views": [value.intent.selection.model_dump(mode="json")]},
            "request_sha256",
        )
    )
    original = value.verifier.resolve_lookup
    calls = []

    def changed(*args):
        current = original(*args)
        calls.append(current)
        return current if len(calls) == 1 else replace(current, truncated=not current.truncated)

    monkeypatch.setattr(value.verifier, "resolve_lookup", changed)
    with pytest.raises(SimilarityContextReadError, match="SOURCE_REVOKED"):
        CatalogPublicSolutionSimilarityRead(value.verifier).prepare_query_in_session(
            value.session,
            EmbeddingRegistryCaller("operator_" + "1" * 32),
            request,
        )
    assert len(calls) == 2
