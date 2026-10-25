"""Real canonical control publication/read with explicit synthetic source/IAM/pair leaves."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.inference_transfer_experiment import VIEWS
from eom_catalog_contracts.reference_query_prepare import (
    parse_supported_reference_query_prepare_request,
)
from eom_catalog_contracts.similarity_context_v2 import parse_supported_similarity_context_request
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryOwnerConfiguration,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import JobRecord
from eom_workflow.reference_query_routed_owner_configuration import (
    RoutedReferenceQueryOwnerConfiguration,
)
from eom_workflow_runner import embedding_batch_plan_admission as admission
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_preparation import ReferenceQueryPreparationUnavailable
from eom_workflow_runner.reference_query_routed_selection import (
    CatalogRoutedReferenceQuerySelection,
)
from eom_workflow_runner.reference_query_source_read import ReferenceQueryOwnerConfiguration
from sqlalchemy import select

from tests.unit.embedding_query_pair_fixtures import paired_query_case
from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


def selection_case(tmp_path, monkeypatch, selected, *, publisher=None):
    body, routing, cpu_policy, cuda_policy = selected
    paired = paired_query_case()
    if publisher is None:
        publication_root = tmp_path / "routed-publication"
        publication_root.mkdir()
        publisher, _engine = _publisher(publication_root)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    routing_pointer = controls.publish_device_routing_policy(
        routing, idempotency_key="synthetic-routed-selection-policy:" + uuid4().hex
    ).member
    body["routing_policy"] = routing_pointer.model_dump(mode="json")
    namespace = body["cpu_configuration"]["namespace"]
    namespace.update(
        storage_partition=paired.selection.scope.storage_partition,
        view="CONTENT_ONLY",
        recipe_sha256=paired.selection.recipe.recipe_sha256,
    )
    body["cpu_configuration"].update(
        corpus_id=paired.selection.corpus_id, recipe=paired.selection.recipe.model_dump(mode="json")
    )
    config = RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    capture = SimpleNamespace(operator_id=paired.selection.scope.actor_id)
    value = SimpleNamespace(
        deny=False,
        pair_denied=False,
        missing=False,
        current_calls=[],
        initial_calls=[],
        publisher=publisher,
        paired=paired,
        configuration=config,
    )
    entries = tuple(embedding_entry(seed) for seed in ("a", "b"))
    by_source = {entry.profile.source_basis.source.item_revision_id: entry for entry in entries}
    owners, contexts = [], []
    for device, policy, pointer, digest in (
        (
            "CPU",
            cpu_policy,
            config.cpu_configuration.native_execution_policy,
            config.cpu_configuration.native_execution_policy_sha256,
        ),
        (
            "CUDA",
            cuda_policy,
            config.cuda_native_execution_policy,
            config.cuda_native_execution_policy_sha256,
        ),
    ):
        ns = type(config.cpu_configuration.namespace).model_validate(
            config.cpu_configuration.namespace.model_dump(mode="json")
            | {"space_sha256": policy.spaces.document.space_sha256}
        )
        registry = EmbeddingRegistryOwnerConfiguration(
            paired.selection.corpus_id,
            ns,
            policy.spaces.document,
            paired.selection.recipe,
            paired.selection.source_classes,
        )
        owner = object.__new__(CatalogReferenceQueryOwnerAdmission)
        owner.configuration = ReferenceQueryOwnerConfiguration(
            registry, pointer, digest, policy.runtime_bundle
        )
        owner.settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        owner.identity = SimpleNamespace(capture=capture, fence_current_operator=Mock())
        owner.catalog = CatalogEmbeddingRegistryVerifier(
            publisher.engine, registry, identity_fence=owner.identity, settings=owner.settings
        )
        rows = []
        template = paired.selection.selected_views(device)[0]
        for ordinal, view in enumerate(VIEWS):
            row_body = template.model_dump(mode="json")
            seed = str(2 * ordinal + (1 if device == "CPU" else 2))
            row_body["view"] = view
            row_body["index"]["index_id"] = "embeddingindex_" + seed * 32
            row_body["index"]["index_revision_id"] = "embeddingindexrev_" + seed * 32
            row_body["index"]["index_manifest"]["artifact_id"] = "artifact_" + seed * 32
            row_body["index"]["index_manifest"]["artifact_revision_id"] = "rev_" + seed * 32
            row_body["index"]["spaces"] = policy.spaces.model_dump(mode="json")
            rows.append(row_body)
        contexts.append(rows)
        owners.append(owner)

        def authorize(session, caller, scope, *, owner=owner):
            assert (
                caller.operator_id == capture.operator_id and session.get_bind() is publisher.engine
            )
            assert scope.namespace == owner.configuration.registry.namespace
            assert scope.graph_snapshot == paired.selection.graph_snapshot
            if value.deny:
                raise ValueError("SYNTHETIC_ACTUAL_SOURCE_DENIED")
            value.current_calls.append(caller.operator_id)

        def resolve(session, caller, choice, *, owner=owner, authorize=authorize):
            authorize(session, caller, choice.scope)
            chosen = tuple(by_source[key] for key in choice.source_revision_ids)
            return ResolvedEmbeddingLookup(
                paired.selection.corpus_id,
                owner.configuration.registry.space,
                paired.selection.recipe,
                tuple(entry.profile.source_basis.source for entry in chosen),
                chosen,
            )

        def initial(session, caller, preparation, *, rows=rows, owner=owner, authorize=authorize):
            authorize(session, caller, preparation.selection.scope)
            value.initial_calls.append(owner.configuration.registry.space.runtime.device)
            anchor = next(
                anchor
                for anchor in paired.selection.anchors
                if anchor.source.item_revision_id == preparation.selection.source_revision_ids[0]
            )
            views = [dict(row) for row in rows]
            if value.missing and owner.configuration.registry.space.runtime.device == "CUDA":
                views[0] = views[0] | {"index": None}
            body = dict(
                schema_version="system-rag-similarity-request/1.0",
                request_id=preparation.request_id,
                consumer_purpose=preparation.consumer_purpose,
                anchor=anchor.model_dump(mode="json"),
                graph_snapshot=preparation.selection.scope.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=preparation.selection.scope.policy_revision_id,
                policy_sha256=preparation.selection.scope.policy_sha256,
                source_classes=list(paired.selection.source_classes),
                topics=[],
                unit_ids=[],
                views=views,
                vector_mode="REQUIRED",
                maximum_sources=1024,
                top_k=8,
            )
            return parse_supported_similarity_context_request(seal(body, "request_sha256"))

        monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
        monkeypatch.setattr(owner.catalog, "resolve_selected_sources", resolve)
        monkeypatch.setattr(owner.catalog, "prepare_reference_query_context_in_session", initial)

    def pair_read(session, caller, **_kwargs):
        assert session.get_transaction().is_active and caller.operator_id == capture.operator_id
        if value.pair_denied:
            raise ValueError("SYNTHETIC_DEVICE_PAIR_MISMATCH")
        return SimpleNamespace(synthetic_pair=True)

    monkeypatch.setattr(admission, "resolve_embedding_device_index_pair", pair_read)
    value.app = CatalogRoutedReferenceQuerySelection(
        cpu=owners[0],
        cuda=owners[1],
        publisher=publisher,
        configuration=config,
        policy=routing,
        cpu_policy=cpu_policy,
        cuda_policy=cuda_policy,
    )
    value.owners, value.routing, value.policies = owners, routing, (cpu_policy, cuda_policy)
    value.requests = tuple(
        parse_supported_reference_query_prepare_request(
            seal(
                dict(
                    schema_version="system-rag-reference-query-prepare-request/1.0",
                    operation="PREPARE_REFERENCE_QUERY",
                    operation_id="queryprepare_" + seed * 32,
                    idempotency_key="original-routed-query:" + seed,
                    source_item_revision_id=anchor.source.item_revision_id,
                    graph_snapshot=paired.selection.graph_snapshot.model_dump(mode="json"),
                    policy_revision_id=paired.selection.access_policy_revision_id,
                    policy_sha256=paired.selection.scope.access_policy_sha256,
                ),
                "request_sha256",
            )
        )
        for seed, anchor in zip(("a", "b"), paired.selection.anchors, strict=True)
    )
    return value


@pytest.fixture
def routed(tmp_path, monkeypatch, selected):
    return selection_case(tmp_path, monkeypatch, selected)


def test_first_selection_and_replay_keep_original_pins_without_new_selection_or_compute(
    routed, monkeypatch
):
    first = routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    assert first.selection.views == VIEWS
    assert tuple(a.source.item_revision_id for a in first.selection.anchors) == tuple(
        r.source_item_revision_id for r in routed.requests
    )
    assert routed.initial_calls == ["CPU", "CUDA"]
    for owner in routed.owners:
        monkeypatch.setattr(
            owner.catalog,
            "prepare_reference_query_context_in_session",
            Mock(side_effect=AssertionError("no mutable head lookup on replay")),
        )
    before = len(routed.current_calls)
    again = routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    assert (again.manifest, again.preparation, again.selection) == (
        first.manifest,
        first.preparation,
        first.selection,
    )
    assert len(routed.current_calls) > before
    with routed.publisher.sessions.begin() as session:
        assert not tuple(
            session.scalars(
                select(JobRecord).where(
                    JobRecord.task_type.in_(("embedding_batch_plan", "native_embedding_launch"))
                )
            )
        )


def test_new_exchange_id_is_same_intent_but_reversed_or_foreign_request_is_not(routed):
    first = routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    changed = tuple(
        parse_supported_reference_query_prepare_request(
            seal(
                r.model_dump(mode="json") | {"operation_id": "queryprepare_" + "f" * 32},
                "request_sha256",
            )
        )
        for r in routed.requests
    )
    assert (
        routed.app.prepare(changed, idempotency_key="original-routed-batch").manifest
        == first.manifest
    )
    with pytest.raises(ValueError, match="REFERENCE_QUERY_ROUTED_SELECTION_INVALID"):
        routed.app.prepare(
            tuple(reversed(routed.requests)), idempotency_key="original-routed-batch"
        )


def test_actual_source_denial_is_checked_before_an_existing_manifest_is_exposed(
    routed, monkeypatch
):
    routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    routed.deny = True
    finder = Mock(side_effect=AssertionError("do not reveal pointer after revoked permission"))
    monkeypatch.setattr(routed.app.controls, "find_routed_reference_query_preparation", finder)
    with pytest.raises(ValueError, match="SYNTHETIC_ACTUAL_SOURCE_DENIED"):
        routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    finder.assert_not_called()


def test_interruption_after_selection_publication_reuses_that_selection_not_new_heads(
    routed, monkeypatch
):
    publish = routed.app.controls.publish_routed_reference_query_preparation
    monkeypatch.setattr(
        routed.app.controls,
        "publish_routed_reference_query_preparation",
        Mock(side_effect=RuntimeError("synthetic interruption before preparation publication")),
    )
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    assert routed.initial_calls == ["CPU", "CUDA"]
    monkeypatch.setattr(routed.app.controls, "publish_routed_reference_query_preparation", publish)
    for owner in routed.owners:
        monkeypatch.setattr(
            owner.catalog,
            "prepare_reference_query_context_in_session",
            Mock(
                side_effect=AssertionError(
                    "do not reselect after an interrupted original selection"
                )
            ),
        )
    completed = routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    assert completed.preparation.parent.selection_manifest.sha256 == sha256_bytes(
        canonical_json_bytes(completed.selection)
    )
    assert completed.preparation.parent.selection_sha256 == completed.selection.selection_sha256
    assert routed.initial_calls == ["CPU", "CUDA"]


@pytest.mark.parametrize("fault", ("missing", "pair_denied"))
def test_missing_or_incompatible_cuda_input_is_not_silently_cpu_fallback(routed, fault):
    setattr(routed, fault, True)
    with pytest.raises((ValueError, ReferenceQueryPreparationUnavailable)):
        routed.app.prepare(routed.requests, idempotency_key="original-routed-batch")
    assert (
        routed.app.controls.find_routed_reference_query_preparation(
            operator_id=routed.owners[0].identity.capture.operator_id,
            idempotency_key="original-routed-batch",
        )
        is None
    )


@pytest.mark.parametrize("fault", ("empty", "list", "duplicate", "too_many", "different_policy"))
def test_bad_group_never_becomes_a_new_source_or_gpu_request(routed, fault):
    requests = routed.requests
    if fault == "empty":
        requests = ()
    elif fault == "list":
        requests = list(requests)
    elif fault == "duplicate":
        requests = (requests[0], requests[0])
    elif fault == "too_many":
        requests = (requests[0],) * 33
    else:
        requests = (
            requests[0],
            parse_supported_reference_query_prepare_request(
                seal(
                    requests[1].model_dump(mode="json") | {"policy_sha256": "sha256:" + "f" * 64},
                    "request_sha256",
                )
            ),
        )
    with pytest.raises(ValueError):
        routed.app.prepare(requests, idempotency_key="original-routed-batch")
    assert not routed.initial_calls


def test_independent_capture_or_namespace_is_not_a_valid_composition(routed):
    cpu, cuda = routed.owners
    cuda.identity = SimpleNamespace(
        capture=SimpleNamespace(operator_id=cpu.identity.capture.operator_id)
    )
    with pytest.raises(ValueError, match="REFERENCE_QUERY_ROUTED_SELECTION_INVALID"):
        CatalogRoutedReferenceQuerySelection(
            cpu=cpu,
            cuda=cuda,
            publisher=routed.publisher,
            configuration=routed.configuration,
            policy=routed.routing,
            cpu_policy=routed.policies[0],
            cuda_policy=routed.policies[1],
        )
