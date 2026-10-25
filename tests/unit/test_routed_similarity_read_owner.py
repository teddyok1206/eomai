"""Explicit installed device/read choices; all Identity and numerical observations synthetic."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_service import similarity_read_runtime as runtime
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead
from eom_workflow_runner.reference_query_source_read import (
    CatalogReferenceQueryReadOwner,
    ReferenceQueryOwnerConfiguration,
    select_completed_reference_query_read_owner,
)
from sqlalchemy import create_engine

from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_routed_similarity_reader_configuration import routed_document
from tests.unit.test_similarity_read_runtime import install_seams


@pytest.fixture
def owners():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    identity = SimpleNamespace(fence_current_operator=Mock())
    cpu, cuda = case(), case(device="CUDA")

    def configuration(query):
        context = query.request.context_request
        return ReferenceQueryOwnerConfiguration(
            EmbeddingRegistryOwnerConfiguration(
                "corpus_" + "a" * 32,
                EmbeddingIndexNamespace(
                    storage_partition=context.views[0].index.storage_partition,
                    space_sha256=query.policy.spaces.document.space_sha256,
                    view=context.views[0].view,
                    recipe_sha256=context.views[0].recipe.recipe_sha256,
                    population_scope="OCCURRENCE_BACKED_PAST_EXAM",
                ),
                query.policy.spaces.document,
                context.views[0].recipe,
                context.source_classes,
            ),
            query.request.native_execution_policy,
            query.policy.policy_sha256,
            query.request.runtime_bundle,
        )

    cuda_owner = CatalogReferenceQueryReadOwner(
        engine, configuration(cuda), identity_fence=identity
    )
    cpu_owner = CatalogReferenceQueryReadOwner(
        engine, configuration(cpu), identity_fence=identity, cuda_owner=cuda_owner
    )
    return SimpleNamespace(
        engine=engine,
        identity=identity,
        cpu=cpu,
        cuda=cuda,
        cpu_owner=cpu_owner,
        cuda_owner=cuda_owner,
    )


def test_completed_request_uses_only_its_installed_device_without_native_authority(owners):
    value = owners
    assert (
        select_completed_reference_query_read_owner(value.cpu_owner, value.cpu.request)
        is value.cpu_owner
    )
    assert (
        select_completed_reference_query_read_owner(value.cpu_owner, value.cuda.request)
        is value.cuda_owner
    )
    reader = CatalogCompletedReferenceQueryRead(
        value.cpu_owner, workflow_id=value.cuda.launch.workflow_id, request=value.cuda.request
    )
    assert reader.owner is value.cuda_owner and reader.request == value.cuda.request
    assert value.cpu_owner.configuration.registry.space == value.cpu.policy.spaces.document
    value.identity.fence_current_operator.assert_not_called()
    assert not any(
        hasattr(reader.owner, name)
        for name in ("resolve_claim", "resolve_submission", "fence_mutation")
    )


def test_missing_cuda_selection_never_uses_cpu_or_creates_execution_permission(owners):
    value = owners
    fixed = CatalogReferenceQueryReadOwner(
        value.engine, value.cpu_owner.configuration, identity_fence=value.identity
    )
    with pytest.raises(ValueError, match="READ_DEVICE_UNAVAILABLE"):
        CatalogCompletedReferenceQueryRead(
            fixed, workflow_id=value.cuda.launch.workflow_id, request=value.cuda.request
        )
    assert select_completed_reference_query_read_owner(fixed, value.cpu.request) is fixed
    value.identity.fence_current_operator.assert_not_called()


@pytest.mark.parametrize(
    "fault", ["identity", "engine", "corpus", "classes", "namespace", "device"]
)
def test_alternate_owner_cannot_broaden_source_identity_or_device(owners, fault):
    value = owners
    configuration = value.cuda_owner.configuration
    identity, engine = value.identity, value.engine
    if fault == "identity":
        identity = SimpleNamespace(fence_current_operator=Mock())
    elif fault == "engine":
        engine = create_engine("sqlite+pysqlite:///:memory:")
    elif fault == "corpus":
        configuration = replace(
            configuration, registry=replace(configuration.registry, corpus_id="corpus_" + "b" * 32)
        )
    elif fault == "classes":
        configuration = replace(
            configuration, registry=replace(configuration.registry, source_classes=("PAST_EXAM",))
        )
        if (
            configuration.registry.source_classes
            == value.cpu_owner.configuration.registry.source_classes
        ):
            configuration = replace(
                configuration,
                registry=replace(
                    configuration.registry, source_classes=("APPROVED_ITEM", "PAST_EXAM")
                ),
            )
    elif fault == "namespace":
        namespace = type(configuration.registry.namespace).model_validate(
            configuration.registry.namespace.model_dump(mode="json") | {"view": "METADATA_ONLY"}
        )
        configuration = replace(
            configuration, registry=replace(configuration.registry, namespace=namespace)
        )
    elif fault == "device":
        configuration = value.cpu_owner.configuration
    other = CatalogReferenceQueryReadOwner(engine, configuration, identity_fence=identity)
    with pytest.raises(ValueError, match="DEVICE_CONFIGURATION_INVALID"):
        CatalogReferenceQueryReadOwner(
            value.engine,
            value.cpu_owner.configuration,
            identity_fence=value.identity,
            cuda_owner=other,
        )


def install_routed_runtime_seams(monkeypatch):
    selected = install_seams(monkeypatch)
    selected.raw = canonical_json_bytes(routed_document())
    selected.read.return_value = selected.raw
    session = Mock()
    session.begin.return_value = nullcontext()
    session_context = Mock(return_value=nullcontext(session))
    monkeypatch.setattr(runtime, "Session", session_context)
    reader = Mock()
    monkeypatch.setattr(runtime.PinnedArtifactReadContext, "for_session", Mock(return_value=reader))

    def read_controls(actual_reader, configuration):
        assert actual_reader is reader
        query = case(device=configuration.registry.space.runtime.device)
        return query.policy, query.bundle

    controls = Mock(side_effect=read_controls)
    monkeypatch.setattr(runtime, "read_pinned_reference_query_controls", controls)
    return SimpleNamespace(**vars(selected), session=session, reader=reader, controls=controls)


def test_runtime_admits_canonical_controls_without_capture_or_gpu_and_keeps_cpu_history(
    monkeypatch,
):
    value = install_routed_runtime_seams(monkeypatch)
    result = runtime.build_catalog_similarity_context_reads(
        value.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(value.raw)
    )
    assert result.owner.cuda_owner is not None
    assert result.owner.cuda_owner.identity is result.owner.identity
    assert result.owner.configuration.registry.space.runtime.device == "CPU"
    assert result.owner.cuda_owner.configuration.registry.space.runtime.device == "CUDA"
    assert value.controls.call_count == 2
    value.reader.revalidate_provenance.assert_called_once()


@pytest.mark.parametrize("fault", ["canonical", "space"])
def test_runtime_rejects_missing_or_mismatched_canonical_controls_not_cpu_fallback(
    monkeypatch, fault
):
    value = install_routed_runtime_seams(monkeypatch)
    if fault == "canonical":
        value.controls.side_effect = ValueError("synthetic missing/hash-denied Artifact")
    else:
        value.controls.side_effect = lambda *_args: (case().policy, case().bundle)
    with pytest.raises(runtime.SimilarityReaderRuntimeError):
        runtime.build_catalog_similarity_context_reads(
            value.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(value.raw)
        )
