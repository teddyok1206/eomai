"""Actual local index2/shard bytes; current source/IAM proof ports are synthetic."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    RESULT_SCHEMA_REF,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.inference_transfer_experiment import experiment_view_text
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingSourceBinding,
    registered_review_embedding_text,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityIndexPinV2,
    SimilarityViewSelectionV2,
)
from eom_catalog_service.embedding_registry_application import read_pinned_embedding_index
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    RegisteredEmbeddingIndexRead,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.embedding_registry_repository import binding_columns
from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferSource
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    embedding_input,
    embedding_result,
    embedding_space,
    seal,
    shard_pointer,
)
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case
from tests.unit.test_embedding_index_assembly_v2 import pointer
from tests.unit.test_embedding_registry_catalog_adapter import OwnerSession, _file_set
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_pinned_similarity_namespace import pinned as pinned
from tests.unit.test_pinned_similarity_namespace import select


@pytest.fixture
def mixed(owner, tmp_path, monkeypatch):
    _old, _session, command, _index, _binding, scope, _root = owner
    entry, _binding2, original_shard, _original_pointer, original_index = mixed_embedding_case(
        "CONTENT_ONLY"
    )
    anchor = embedding_entry()
    native = embedding_input(
        experiment_view_text(anchor, "CONTENT_ONLY"),
        registered_review_embedding_text(entry, "CONTENT_ONLY"),
    )
    one = (1.0,) + (0.0,) * (original_shard.dimension - 1)
    binary = pack_unit_vectors((one, one), dimension=original_shard.dimension)
    shard_body = original_shard.model_dump(mode="json")
    shard_body["binary"]["sha256"] = sha256_bytes(binary)
    shard = EmbeddingVectorShardManifest.model_validate(seal(shard_body, "shard_sha256"))
    member = shard_pointer(shard)
    bindings = []
    for original in original_index.bindings:
        body = original.model_dump(mode="json")
        body["row_ref"]["shard_manifest"] = member.model_dump(mode="json")
        body["policy_revision_id"] = original_index.bindings[0].policy_revision_id
        body["policy_sha256"] = original_index.bindings[0].policy_sha256
        bindings.append(type(original).model_validate(seal(body, "binding_sha256")))
    index_body = original_index.model_dump(mode="json")
    index_body.update(
        shards=[member.model_dump(mode="json")],
        bindings=[value.model_dump(mode="json") for value in bindings],
    )
    index = MixedEmbeddingIndexManifest.model_validate(seal(index_body, "index_sha256"))
    manifest = pointer(index)
    result = embedding_result(native, shard=shard)
    root = tmp_path / "mixed"
    records = (
        *_file_set(
            root,
            member.artifact_id,
            member.artifact_revision_id,
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
                    member.schema_ref,
                    "application/json",
                ),
                "vectors.f32": (binary, shard.binary.schema_ref, "application/octet-stream"),
            },
            "c",
        ),
        *_file_set(
            root,
            manifest.artifact_id,
            manifest.artifact_revision_id,
            "control_embedding_index",
            "index.json",
            {
                "index.json": (
                    canonical_json_bytes(index.model_dump(mode="json")),
                    manifest.schema_ref,
                    "application/json",
                ),
            },
            "d",
        ),
    )
    session = OwnerSession(command, *records)
    session.in_transaction = lambda: session.root.is_active
    namespace = MixedEmbeddingIndexNamespace(
        storage_partition=index.storage_partition,
        space_sha256=index.space.space_sha256,
        view=index.view,
        recipe_sha256=index.recipe.recipe_sha256,
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    verifier = CatalogEmbeddingRegistryVerifier(
        _old.engine,
        replace(
            _old.configuration, namespace=namespace, source_classes=("APPROVED_ITEM", "PAST_EXAM")
        ),
        identity_fence=_old.identity_fence,
        settings=CatalogSettings(nas_artifact_root=root),
    )
    current = ResolvedEmbeddingLookup(
        command.corpus_id,
        index.space,
        index.recipe,
        (anchor.profile.source_basis.source, entry.profile.source_basis.source),
        (anchor, entry),
        base_analysis_run_ids=(
            (
                anchor.profile.source_basis.source.item_revision_id,
                anchor.profile.source_basis.solution_evidence.base_analysis_run_id,
            ),
            (entry.profile.source_basis.source.item_revision_id, "analysisrun_" + "c" * 32),
        ),
    )
    # Existing real owner uses the same admitted corpus value shape. No model or
    # schema pointer supplies IAM; these two injected ports are explicitly synthetic.
    from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferCorpus

    corpus = AdmittedInferenceTransferCorpus(
        (anchor.profile,),
        (),
        False,
        0,
        tuple(
            AdmittedInferenceTransferSource(base, source)
            for source, base in zip(
                current.sources,
                (
                    anchor.profile.source_basis.solution_evidence.base_analysis_run_id,
                    "analysisrun_" + "c" * 32,
                ),
                strict=True,
            )
        ),
    )

    def capture(session, command, recipe, **options):
        options["artifact_reader"].require_session(session)
        options["identity_fence"].fence_current_operator(session, command.actor_id)
        return (
            InferenceTransferSessionCapture(scope)
            if options.get("phase") is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            else InferenceTransferSessionCapture(scope, corpus, (anchor,))
        )

    verifier.sources.capture_in_session = Mock(side_effect=capture)
    monkeypatch.setattr(verifier, "_captured_lookup", Mock(return_value=current))
    selection = SimilarityViewSelectionV2(
        view=index.view,
        recipe=index.recipe,
        index=SimilarityIndexPinV2(
            index_id=index.index_id,
            index_revision_id=index.index_revision_id,
            index_manifest=manifest,
            index_sha256=index.index_sha256,
            storage_partition=index.storage_partition,
            spaces=ReferenceQuerySpaces(
                query=embedding_space(purpose="QUERY"), document=index.space
            ),
        ),
    )
    intent = EmbeddingRegistryRead(
        EmbeddingRegistryLookup(
            command.corpus_id,
            namespace,
            index.bindings[0].graph_snapshot,
            index.bindings[0].policy_revision_id,
            index.bindings[0].policy_sha256,
        ),
        selection,
    )
    registered = RegisteredEmbeddingIndexRead(
        command.corpus_id,
        namespace,
        index.index_id,
        index.index_revision_id,
        manifest,
        index.index_sha256,
        intent.scope.graph_snapshot.graph_snapshot_revision_id,
        intent.scope.policy_revision_id,
        intent.scope.policy_sha256,
        2,
        content_sha256([value.binding_sha256 for value in index.bindings]),
    )
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_application.EmbeddingRegistryRepository.read_pinned_revision",
        lambda self, index_id, index_revision_id: registered,
    )
    # Ledger metadata is synthetic, while the owner dereferences actual local
    # index/shard/result/vector bytes and applies the normal application checks.
    ledger = {
        value.binding_sha256: EmbeddingSourceBindingRecord(
            **binding_columns(value),
            **{
                "binding_manifest_" + name: field
                for name, field in manifest.model_dump(mode="python").items()
            },
        )
        for value in index.bindings
    }
    encoded = {
        value.encoding.encoding_sha256: EmbeddingEncodingRecord(
            **value.encoding.model_dump(mode="python"),
            **{"shard_" + name: field for name, field in member.model_dump(mode="python").items()},
            row_index=value.row_ref.row_index,
        )
        for value in index.bindings
    }
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_application.EmbeddingRegistryRepository.bindings",
        lambda self, keys: ledger,
    )
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_application.EmbeddingRegistryRepository.encodings",
        lambda self, keys: encoded,
    )
    return SimpleNamespace(
        verifier=verifier,
        session=session,
        intent=intent,
        registered=registered,
        current=current,
        index=index,
        manifest=manifest,
        root=root,
        entry=entry,
    )


def test_actual_index2_and_numeric1_files_resolve_registered_profile2_without_retag(mixed):
    result = read_pinned_embedding_index(
        mixed.session, EmbeddingRegistryCaller("operator_" + "1" * 32), mixed.intent, mixed.verifier
    )
    assert len(result.bindings) == 2 and len(result.numerical_rows) == 2
    assert any(
        isinstance(value, RegisteredReviewEmbeddingSourceBinding) for value in result.bindings
    )
    assert {value.profile.schema_ref for value in result.profiles} == {
        "eom://schemas/knowledge/item-inference-transfer/1.0",
        "eom://schemas/knowledge/item-inference-transfer/2.0",
    }
    assert mixed.verifier._captured_lookup.call_count == 1


@pytest.mark.parametrize("fault", ["wrong_base", "revoked_artifact", "tamper"])
def test_actual_mixed_bytes_base_and_producer_fences_remain_mandatory(mixed, fault):
    if fault == "wrong_base":
        mixed.verifier._captured_lookup.return_value = replace(
            mixed.current,
            base_analysis_run_ids=(
                (
                    mixed.entry.profile.source_basis.source.item_revision_id,
                    "analysisrun_" + "f" * 32,
                ),
            ),
        )
    elif fault == "revoked_artifact":
        mixed.session.records[(ArtifactRecord, mixed.manifest.artifact_id)].approved = False
    else:
        path = (
            mixed.root
            / mixed.manifest.artifact_id
            / mixed.manifest.artifact_revision_id
            / "index.json"
        )
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b" ")
    with pytest.raises(EmbeddingRegistryError):
        read_pinned_embedding_index(
            mixed.session,
            EmbeddingRegistryCaller("operator_" + "1" * 32),
            mixed.intent,
            mixed.verifier,
        )


def test_real_old_artifact_pin_reads_under_current_mixed_without_mutating_primary(pinned):
    old = pinned.verifier.configuration
    namespace = MixedEmbeddingIndexNamespace.model_validate(
        old.namespace.model_dump(mode="json")
        | {"projection_version": "mixed-solution-comparison/2.0"}
    )
    configured = replace(old, namespace=namespace, source_classes=("APPROVED_ITEM", "PAST_EXAM"))
    pinned.verifier.configuration = configured
    selected = select(pinned)
    assert selected.configuration.namespace == pinned.registered.namespace
    assert selected.configuration.source_classes == ("PAST_EXAM",)
    assert pinned.verifier.configuration is configured
    assert pinned.reads == [((pinned.registered.index_id, pinned.registered.index_revision_id),)]
    assert all(
        call.args[1].source_classes == ("PAST_EXAM",)
        for call in selected.sources.capture_in_session.call_args_list
    )


def test_historical_old_policy_or_actor_denial_is_not_replaced_by_mixed_current(pinned):
    old = pinned.verifier.configuration
    namespace = MixedEmbeddingIndexNamespace.model_validate(
        old.namespace.model_dump(mode="json")
        | {"projection_version": "mixed-solution-comparison/2.0"}
    )
    pinned.verifier.configuration = replace(
        old, namespace=namespace, source_classes=("APPROVED_ITEM", "PAST_EXAM")
    )
    pinned.verifier.identity_fence.fence_current_operator.side_effect = ValueError(
        "revoked original policy"
    )
    with pytest.raises(EmbeddingRegistryError):
        select(pinned)
    assert pinned.reads == []
