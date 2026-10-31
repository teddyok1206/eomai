"""Real source/index file reads and canonical controls, with explicit synthetic IAM leaves."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
from eom_catalog_service import public_solution_similarity_read as reads
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryOwnerConfiguration,
    RegisteredEmbeddingIndexRead,
    ResolvedEmbeddingLookup,
    SelectedEmbeddingSources,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow.reference_query_routed_owner_configuration import (
    PublicRoutedReferenceQueryOwnerConfiguration,
)
from eom_workflow_runner import embedding_batch_plan_admission as admission
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_routed_selection import (
    CatalogRoutedReferenceQuerySelection,
)
from eom_workflow_runner.reference_query_source_read import ReferenceQueryOwnerConfiguration
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_public_solution_index_assembly import setup
from tests.unit.test_public_solution_query_owner_configuration import public as public
from tests.unit.test_public_solution_registry_read import public_read as public_read
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


def test_bulk_prepare_reads_one_real_canonical_index_and_keeps_source_order(
    public_read, monkeypatch
):
    value = public_read
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    inputs = tuple(
        reads.PublicSolutionSimilarityPreparation(
            f"similarityrequest_{ordinal + 1:032x}",
            SelectedEmbeddingSources(value.intent.scope, (entry.source.item_revision_id,)),
            value.intent.selection.index.spaces,
            "ITEM_DATABASE_SEARCH",
            8,
        )
        for ordinal, entry in enumerate(reversed(value.entries))
    )
    official = Mock(wraps=reads.read_pinned_embedding_index)
    monkeypatch.setattr(reads, "read_pinned_embedding_index", official)
    result = reads.CatalogPublicSolutionSimilarityRead(value.verifier).prepare_many_in_session(
        value.session, caller, inputs
    )
    assert tuple(row.anchor.source.item_revision_id for row in result) == tuple(
        preparation.selection.source_revision_ids[0] for preparation in inputs
    )
    assert all(row.views[0].index.index_manifest == value.index_member for row in result)
    assert official.call_count == 1
    with pytest.raises(ValueError):
        reads.CatalogPublicSolutionSimilarityRead(value.verifier).prepare_many_in_session(
            value.session, caller, (inputs[0], inputs[0])
        )
    assert official.call_count == 1


def public_selection_case(
    tmp_path,
    monkeypatch,
    public,
    *,
    publisher=None,
    identity="a" * 32,
    entries=None,
    registered_devices=(),
):
    body, routing, cpu_policy, cuda_policy, _primary = public
    if publisher is None:
        publication_root = tmp_path / "public-query-controls"
        publication_root.mkdir()
        publisher, engine = _publisher(publication_root)
        publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    else:
        engine = publisher.engine
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    body["routing_policy"] = controls.publish_device_routing_policy(
        routing, idempotency_key="synthetic-public-routing-policy:" + identity
    ).member.model_dump(mode="json")
    config = PublicRoutedReferenceQueryOwnerConfiguration.model_validate(body)
    template = public_similarity_case()[0]
    entries = setup()[0] if entries is None else entries
    by_id = {entry.source.item_revision_id: entry for entry in entries}
    capture = NS(operator_id="operator_" + "1" * 32)
    value = NS(deny=False, heads=Mock(), index_reads=Mock(), publisher=publisher, engine=engine)
    owners, registered = [], {}
    for seed, policy, pointer, digest in (
        (
            "c",
            cpu_policy,
            config.cpu_configuration.native_execution_policy,
            cpu_policy.policy_sha256,
        ),
        ("d", cuda_policy, config.cuda_native_execution_policy, cuda_policy.policy_sha256),
    ):
        ns = config.cpu_configuration.namespace.model_copy(
            update={"space_sha256": policy.spaces.document.space_sha256}
        )
        registry = EmbeddingRegistryOwnerConfiguration(
            config.cpu_configuration.corpus_id,
            ns,
            policy.spaces.document,
            config.cpu_configuration.recipe,
            config.cpu_configuration.source_classes,
        )
        owner = object.__new__(CatalogReferenceQueryOwnerAdmission)
        owner.configuration = ReferenceQueryOwnerConfiguration(
            registry, pointer, digest, policy.runtime_bundle
        )
        owner.settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        owner.identity = NS(capture=capture, fence_current_operator=Mock())
        owner.catalog = CatalogEmbeddingRegistryVerifier(
            engine, registry, identity_fence=owner.identity, settings=owner.settings
        )

        def authorize(session, caller, scope, *, namespace=ns):
            assert session.get_bind() is engine and caller.operator_id == capture.operator_id
            assert scope.namespace == namespace and scope.maximum_sources == 16384
            if value.deny:
                raise ValueError("SYNTHETIC_PUBLIC_SOURCE_DENIED")

        def resolve(session, caller, selection, *, owner=owner, authorize=authorize):
            authorize(session, caller, selection.scope)
            picked = tuple(by_id[key] for key in selection.source_revision_ids)
            return ResolvedEmbeddingLookup(
                owner.configuration.registry.corpus_id,
                owner.configuration.registry.space,
                owner.configuration.registry.recipe,
                tuple(entry.source for entry in picked),
                picked,
            )

        monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
        monkeypatch.setattr(owner.catalog, "resolve_selected_sources", resolve)
        index = template.views[0].index
        member = index.index_manifest.model_copy(
            update={
                "artifact_id": "artifact_" + seed * 32,
                "artifact_revision_id": "rev_" + seed * 32,
                "schema_ref": "eom://schemas/knowledge/embedding-index-manifest/4.0"
                if policy.spaces.document.runtime.device in registered_devices
                else index.index_manifest.schema_ref,
            }
        )
        registered[ns.space_sha256] = RegisteredEmbeddingIndexRead(
            registry.corpus_id,
            ns,
            "embeddingindex_" + seed * 32,
            "embeddingindexrev_" + seed * 32,
            member,
            index.index_sha256,
            template.graph_snapshot.graph_snapshot_revision_id,
            template.policy_revision_id,
            template.policy_sha256,
            len(entries),
            content_sha256({"synthetic_bindings": seed}),
        )
        owners.append(owner)

    def head(_self, corpus, namespace):
        value.heads(corpus, namespace)
        return registered[namespace.space_sha256], 1

    monkeypatch.setattr(reads.EmbeddingRegistryRepository, "current_namespace_revision", head)
    monkeypatch.setattr(reads, "read_pinned_embedding_index", value.index_reads)
    monkeypatch.setattr(
        admission,
        "resolve_public_solution_device_indexes",
        lambda *_args, **_kw: NS(synthetic_pair=True),
    )
    value.app = CatalogRoutedReferenceQuerySelection(
        cpu=owners[0],
        cuda=owners[1],
        publisher=publisher,
        configuration=config,
        policy=routing,
        cpu_policy=cpu_policy,
        cuda_policy=cuda_policy,
    )
    value.request = ReferenceQueryPrepareRequestV4.model_validate(
        seal(
            dict(
                schema_version="system-rag-reference-query-prepare-request/4.0",
                operation="PREPARE_REFERENCE_QUERY",
                operation_id="queryprepare_" + identity,
                idempotency_key="synthetic-public-selection-key:" + identity,
                source_item_revision_ids=list(reversed(tuple(by_id))),
                graph_snapshot=template.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=template.policy_revision_id,
                policy_sha256=template.policy_sha256,
                consumer_purpose="ITEM_DATABASE_SEARCH",
                top_k=8,
            ),
            "request_sha256",
        )
    )
    return value


@pytest.fixture(params=[False, True], ids=["public3", "registered4"])
def chosen(public, tmp_path, monkeypatch, request):
    from tests.unit.test_registered_public_solution_index import registered_index_entry

    value = public_selection_case(
        tmp_path,
        monkeypatch,
        public,
        entries=(*setup()[0], registered_index_entry()) if request.param else None,
        registered_devices=("CUDA",) if request.param else (),
    )
    value.expected_parent_protocol = (
        "embedding-batch-plan/1.5" if request.param else "embedding-batch-plan/1.4"
    )
    value.expected_preparation_protocol = (
        "reference-query-routed-preparation/3.0"
        if request.param
        else "reference-query-routed-preparation/2.0"
    )
    yield value
    value.engine.dispose()


def test_public_selection_preserves_its_family_and_replay_never_selects_latest(chosen):
    value = chosen
    first = value.app.prepare_public(value.request)
    assert first.selection.schema_version == value.expected_parent_protocol
    assert first.preparation.schema_version == value.expected_preparation_protocol
    assert (
        tuple(anchor.source.item_revision_id for anchor in first.selection.anchors)
        == value.request.source_item_revision_ids
    )
    with value.publisher.sessions() as session:
        count = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
    assert value.heads.call_count == value.index_reads.call_count == 2
    replay = value.app.prepare_public(value.request)
    assert (replay.manifest, replay.preparation, replay.selection, replay.routing_policy) == (
        first.manifest,
        first.preparation,
        first.selection,
        first.routing_policy,
    )
    assert value.heads.call_count == value.index_reads.call_count == 2
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == count
    value.deny = True
    with pytest.raises(ValueError, match="PUBLIC_SOURCE_DENIED"):
        value.app.prepare_public(value.request)


def test_public_same_key_with_different_intent_cannot_allocate_new_work(chosen):
    first = chosen.app.prepare_public(chosen.request)
    changed = ReferenceQueryPrepareRequestV4.model_validate(
        seal(chosen.request.model_dump(mode="json") | {"top_k": 9}, "request_sha256")
    )
    with pytest.raises(ValueError, match="ROUTED_SELECTION_INVALID"):
        chosen.app.prepare_public(changed)
    assert chosen.heads.call_count == chosen.index_reads.call_count == 2
    replay = chosen.app.prepare_public(chosen.request)
    assert (replay.manifest, replay.preparation, replay.selection, replay.routing_policy) == (
        first.manifest,
        first.preparation,
        first.selection,
        first.routing_policy,
    )
