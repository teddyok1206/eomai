"""Anchor-scope operation counts and real temporary Artifact integrity; synthetic IAM/SQL."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_registry_catalog_adapter as owner_module
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapturePhase,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_registry_catalog_adapter import _read_selection
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_reference_query_owner_admission import source as source


def test_native_input_bytes_ignore_unrelated_population_but_retain_exact_anchor(
    source, monkeypatch
):
    from eom_identifiers import canonical_json_bytes
    from eom_workflow_runner.reference_query_owner_admission import (
        build_reference_query_native_input,
    )

    monkeypatch.setattr(
        source.owner.catalog,
        "prepare_and_read_similarity_context_in_session",
        lambda *_a: pytest.fail("native QUERY must not materialize the ranking population"),
    )
    with source.publisher.sessions.begin() as session:
        full = source.owner.resolve_sources(session, source.request)
    prepared = full.prepared
    anchor_id = full.request.context_request.anchor.source.item_revision_id
    anchor = replace(
        full,
        prepared=replace(
            prepared,
            sources=tuple(
                value for value in prepared.sources if value.source.item_revision_id == anchor_id
            ),
            graph_scores=(),
            graph_evidence=None,
            truncated=False,
        ),
    )
    assert len(anchor.prepared.sources) == 1 < len(full.prepared.sources)
    identifiers = {"job_id": "job_" + "e" * 32, "query_request_id": "embeddingquery_" + "e" * 32}
    original = build_reference_query_native_input(full, **identifiers)
    narrowed = build_reference_query_native_input(anchor, **identifiers)
    assert canonical_json_bytes(narrowed.model_dump(mode="json")) == canonical_json_bytes(
        original.model_dump(mode="json")
    )
    assert narrowed.request_sha256 == original.request_sha256


@pytest.mark.parametrize("population_size", (2, 520, 1024))
@pytest.mark.parametrize("query_only", (False, True))
def test_query_anchor_source_materialization_is_bounded_not_population_coverage(
    owner, monkeypatch, population_size, query_only
):
    """Operation-count benchmark with synthetic source admission, not a latency claim."""
    from contextlib import nullcontext

    from eom_catalog_service.embedding_registry_ports import ResolvedPinnedEmbeddingIndex

    from tests.unit.test_similarity_context_service import CALLER, case

    verifier, session, *_ = owner
    request, _sources, _query = case()
    monkeypatch.setattr(session, "no_autoflush", nullcontext(), raising=False)
    original = verifier.sources.capture_in_session
    materialized = []
    selected_scopes = []
    captures = []
    anchor_id = request.anchor.source.item_revision_id

    def capture(actual_session, command, recipe, **options):
        selection = command.source_revision_ids
        selected_scopes.append(selection)
        value = original(actual_session, command, recipe, **options)
        if options["phase"] is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
            return value
        assert value.corpus is not None
        captures.append(value)
        base = value.corpus.sources[0]
        # Selection is already present in admission input, before expensive source IO.
        if selection:
            assert selection == (anchor_id,)
            admitted = value.corpus.sources
        else:
            admitted = (
                base,
                *(
                    replace(
                        base,
                        source=base.source.model_copy(
                            update={
                                "item_id": f"item_{index:032x}",
                                "item_revision_id": f"itemrev_{index:032x}",
                            }
                        ),
                    )
                    for index in range(population_size - 1)
                ),
            )
        materialized.append(len(admitted))
        return replace(
            value,
            corpus=replace(
                value.corpus, sources=admitted, missing_solution_reports=len(admitted) - 1
            ),
        )

    def read(actual_session, caller, intent, read_owner):
        read_owner.authorize_scope(actual_session, caller, intent.scope)
        _reader, value = read_owner._capture(
            actual_session,
            caller,
            intent.scope,
            InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
        )
        read_owner.authorize_scope(actual_session, caller, intent.scope)
        return ResolvedPinnedEmbeddingIndex(
            intent, tuple(item.source for item in value.corpus.sources), (), (), ()
        )

    monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
    monkeypatch.setattr(owner_module, "read_pinned_embedding_index", read)
    if query_only:
        prepared = verifier.prepare_reference_query_anchor_in_session(session, CALLER, request)
        assert materialized == [1, 1]
        assert selected_scopes == [(anchor_id,)] * 11
        assert len(prepared.sources) == 1
    else:
        prepared, _reads = verifier.prepare_and_read_similarity_context_in_session(
            session, CALLER, request
        )
        assert materialized == [population_size, population_size]
        assert selected_scopes == [()] * 11
        assert len(prepared.sources) == population_size
    assert len(captures) == 2 and not prepared.truncated


@pytest.mark.parametrize(
    "fault", ("none", "revoked_at_end", "missing_index", "index_hash", "binary")
)
def test_query_anchor_retains_actual_registered_index_and_numeric_validation(
    owner, monkeypatch, fault
):
    from contextlib import nullcontext

    from eom_catalog_contracts.similarity_context import parse_similarity_context_request
    from eom_catalog_service import embedding_registry_application as application
    from eom_catalog_service.similarity_context_ports import SimilarityContextReadError

    from tests.unit.test_similarity_context_service import CALLER, case

    verifier, session, command, index, binding, _scope, root = owner
    request, _sources, _query = case()
    intent, registered = _read_selection(command, index)
    request = parse_similarity_context_request(
        seal(
            request.model_dump(mode="json") | {"views": [intent.selection.model_dump(mode="json")]},
            "request_sha256",
        )
    )
    monkeypatch.setattr(session, "no_autoflush", nullcontext(), raising=False)
    monkeypatch.setattr(session, "in_transaction", lambda: True, raising=False)
    if fault == "missing_index":
        registered = None
    elif fault == "index_hash":
        registered = replace(registered, index_sha256="sha256:" + "f" * 64)
    elif fault == "binary":
        target = (
            root
            / index.shards[0].artifact_id
            / index.shards[0].artifact_revision_id
            / "vectors.f32"
        )
        target.write_bytes(target.read_bytes()[:-1])
    monkeypatch.setattr(
        owner_module.EmbeddingRegistryRepository, "read_pinned_revision", lambda *_a: registered
    )
    # Registry rows are a synthetic seam; member hashes and numerical bytes are real.
    monkeypatch.setattr(
        owner_module.EmbeddingRegistryRepository,
        "bindings",
        lambda *_a: {
            binding.binding_sha256: SimpleNamespace(**application._binding_columns(binding))
        },
    )
    encoded = SimpleNamespace(
        **binding.encoding.model_dump(mode="python"),
        row_index=binding.row_ref.row_index,
        **{
            "shard_" + name: value
            for name, value in binding.row_ref.shard_manifest.model_dump(mode="python").items()
        },
    )
    monkeypatch.setattr(
        owner_module.EmbeddingRegistryRepository,
        "encodings",
        lambda *_a: {binding.encoding.encoding_sha256: encoded},
    )
    if fault == "revoked_at_end":
        original = verifier.sources.capture_in_session
        counts = []

        def capture(*args, **options):
            value = original(*args, **options)
            if options["phase"] is InferenceTransferSessionCapturePhase.CAPTURE_POPULATION:
                counts.append(None)
                if len(counts) == 2:
                    return replace(value, corpus=replace(value.corpus, sources=()), entries=())
            return value

        monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
        with pytest.raises(SimilarityContextReadError, match="SOURCE_REVOKED"):
            verifier.prepare_reference_query_anchor_in_session(session, CALLER, request)
    elif fault == "none":
        result = verifier.prepare_reference_query_anchor_in_session(session, CALLER, request)
        assert len(result.sources) == 1 and result.sources[0].source == binding.source
    else:
        with pytest.raises(SimilarityContextReadError, match="INDEX_POINTER_INVALID"):
            verifier.prepare_reference_query_anchor_in_session(session, CALLER, request)
