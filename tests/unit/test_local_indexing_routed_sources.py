"""Actual Catalog/owner/control IO composition; service/source SQL leaves are synthetic."""

from copy import copy, deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service import PostgresLocalIndexingServiceFence
from eom_identity_service.local_indexing_fence_sql import LocalIndexingFenceOwnerPin
from eom_identity_service.local_indexing_runtime import (
    AuthenticatedLocalIndexingRuntime,
    LocalIndexingRuntimePin,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_indexing_routed_owner_configuration import (
    RoutedLocalIndexingOwnerConfiguration,
    validate_supported_routed_indexing_configuration,
)
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.local_indexing_routed_sources import (
    PairedIndexingNamespacePreparation,
    build_routed_indexing_sources,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_indexing_routed_owner_configuration import routed_document
from tests.unit.test_public_solution_indexing_owner import public_owner_document


@pytest.fixture
def routed_publisher(tmp_path):
    return _publisher(tmp_path)


@pytest.fixture
def routed(tmp_path, monkeypatch, request, routed_publisher):
    public = getattr(request, "param", None) in {"public", "registered_public"}
    body, policy = public_owner_document() if public else routed_document()
    publisher, engine = routed_publisher
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    cohort = uuid4().hex
    source_commit = cohort + "a" * 8
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit=source_commit)
    saved = controls.publish_device_routing_policy(
        policy, idempotency_key="test:routed-device-policy:" + cohort
    )
    body["routing_policy"] = saved.member.model_dump(mode="json")
    base = service_fixture()
    pin = LocalIndexingRuntimePin(base.grant.service, source_commit, "sha256:" + "3" * 64)
    fence = PostgresLocalIndexingServiceFence(
        LocalIndexingFenceOwnerPin("synthetic_owner", 12001),
        pin,
        object.__new__(AuthenticatedLocalIndexingRuntime),
    )
    current = SimpleNamespace(published=True, bad_device=None, deny=False, observed=[])
    guard = Mock()

    def current_service(_self, session):
        assert session.in_transaction()
        guard()
        if current.deny:
            raise PermissionError("synthetic service revoked")

    monkeypatch.setattr(PostgresLocalIndexingServiceFence, "fence_current_service", current_service)
    grants = {}
    for device, selected_profile in (("CPU", policy.cpu.profile), ("CUDA", policy.cuda.profile)):
        profiles, default_device = [selected_profile.model_dump(mode="json")], device
        if device == "CUDA" and getattr(request, "param", None) == "native_default":
            profiles, default_device = (
                [
                    policy.cpu.profile.model_dump(mode="json"),
                    policy.cuda.profile.model_dump(mode="json"),
                ],
                "CPU",
            )
        native = LocalEmbeddingServiceExecutionPolicy.model_validate(
            seal(
                base.policy.model_dump(mode="json")
                | dict(
                    profiles=profiles,
                    default_device=default_device,
                ),
                "policy_sha256",
            )
        )
        saved_native = controls.publish_service_policy(
            native,
            idempotency_key="test:routed-native-policy:" + device + ":" + cohort,
            created_at=native.created_at,
        )
        destination = body["cpu_configuration"] if device == "CPU" else body["cuda_grants"][0]
        destination["native_execution_policy"] = saved_native.member.model_dump(mode="json")
        destination["native_execution_policy_sha256"] = native.policy_sha256
        ns = deepcopy(body["cpu_configuration"]["namespace"])
        ns["space_sha256"] = selected_profile.space.space_sha256
        grant_type = PublicSolutionIndexingAccessPolicy if public else type(base.grant)
        grant = grant_type.model_validate(
            seal(
                base.grant.model_dump(mode="json")
                | dict(
                    access_policy_revision_id=destination["service_policy_revision_id"],
                    runtime_configuration_sha256=pin.configuration_sha256,
                    corpus_id=body["cpu_configuration"]["corpus_id"],
                    namespaces=[ns],
                    space=selected_profile.space.model_dump(mode="json"),
                    recipe=body["cpu_configuration"]["recipe"],
                    native_execution_policy_sha256=native.policy_sha256,
                    resource_profile_sha256=selected_profile.resource_profile.resource_profile_sha256,
                    **(
                        {
                            "schema_version": "education-retrieval-access-policy/1.4",
                            "maximum_sources": body["cpu_configuration"]["maximum_sources"],
                            "maximum_page_sources": 1024,
                            "answer_bearing_use": "VERIFIABLE_PUBLIC_SOLUTION_ONLY",
                            "source_classes": body["cpu_configuration"]["source_classes"],
                        }
                        if public
                        else {}
                    ),
                    **(
                        {
                            "source_access_policy_revision_id": "accessrev_" + "e" * 32,
                            "source_access_policy_sha256": "sha256:" + "e" * 64,
                        }
                        if device == "CUDA" and getattr(request, "param", None) == "source_policy"
                        else {}
                    ),
                    **(
                        {"source_classes": ["APPROVED_ITEM", "PAST_EXAM"]}
                        if device == "CUDA"
                        and getattr(request, "param", None) == "wider_source_classes"
                        else {}
                    ),
                ),
                "content_sha256",
            )
        )
        destination["service_policy_sha256"] = grant.content_sha256
        grants[grant.access_policy_revision_id] = grant

    def current_graph(authority, session, revision, sha):
        authority.service_fence.fence_current_service(session)
        grant = grants[revision]
        assert grant.content_sha256 == sha
        current.observed.append(grant.space.runtime.device)
        graph = base.request.graph_snapshot
        if grant.space.runtime.device == current.bad_device:
            revision = graph.graph_snapshot_revision_id
            graph = type(graph).model_validate(
                graph.model_dump(mode="json")
                | {
                    "graph_snapshot_revision_id": revision[:-1]
                    + ("f" if revision[-1] != "f" else "e")
                }
            )
        return grant, graph if current.published else None

    def authorize_scope(authority, session, intent):
        authority.service_fence.fence_current_service(session)
        grant = grants[intent.service_policy_revision_id]
        assert intent.service_policy_sha256 == grant.content_sha256
        assert intent.namespace in grant.namespaces and intent.space == grant.space
        assert intent.native_execution_policy_sha256 == grant.native_execution_policy_sha256
        return grant

    monkeypatch.setattr(CatalogLocalIndexingSourceAuthority, "current_graph", current_graph)
    monkeypatch.setattr(CatalogLocalIndexingSourceAuthority, "authorize_scope", authorize_scope)
    by_space = {g.space.space_sha256: g for g in grants.values()}

    def catalog_scope(verifier, session, caller, query):
        # Explicit synthetic Graph/IAM SQL seam; canonical control IO stays real.
        fence.fence_current_service(session)
        grant = by_space[verifier.configuration.space.space_sha256]
        assert caller.service == grant.service and query.namespace in grant.namespaces
        assert query.policy_sha256 == grant.source_access_policy_sha256

    monkeypatch.setattr(CatalogEmbeddingRegistryVerifier, "authorize_scope", catalog_scope)
    body["cuda_grants"][0]["cpu_service_policy_revision_id"] = body["cpu_configuration"][
        "service_policy_revision_id"
    ]
    selected = validate_supported_routed_indexing_configuration(body)
    settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)

    def build(configuration=selected):
        return build_routed_indexing_sources(
            engine, publisher, fence, configuration, source_commit=source_commit, settings=settings
        )

    yield SimpleNamespace(
        registered_public=getattr(request, "param", None) == "registered_public",
        build=build,
        body=body,
        selected=selected,
        current=current,
        grants=grants,
        guard=guard,
        fence=fence,
        publisher=publisher,
        engine=engine,
        settings=settings,
    )
    engine.dispose()


def test_actual_catalog_owner_and_prepare_objects_use_separate_exact_spaces_and_grants(routed):
    value = routed.build()
    assert len(value.namespaces) == 1
    pair = value.namespaces[0]
    assert type(pair.cpu.owner) is type(pair.cuda.owner) is CatalogLocalEmbeddingOwnerAdmission
    assert pair.cpu.owner.catalog.engine is pair.cuda.owner.catalog.engine is routed.engine
    assert pair.cpu.runtime_profile.space != pair.cuda.runtime_profile.space
    assert (
        pair.cpu.owner.configuration.native_execution_policy
        != pair.cuda.owner.configuration.native_execution_policy
    )
    assert not hasattr(pair.cpu, "executor") and not hasattr(pair.cuda, "executor")
    assert routed.current.observed == ["CPU", "CUDA"]
    assert value.policy.policy_sha256 == routed.selected.routing_policy_sha256


def test_empty_published_head_does_not_create_work_or_skip_current_service_fence(routed):
    routed.current.published = False
    value = routed.build()
    assert len(value.namespaces) == 1 and routed.guard.call_count >= 4


def test_different_current_graph_is_not_silently_paired_or_retried_on_cpu(routed):
    routed.current.bad_device = "CUDA"
    with pytest.raises(ValueError, match="LOCAL_INDEXING_ROUTED_SOURCE_MISMATCH"):
        routed.build()
    assert routed.current.observed == ["CPU", "CUDA"]


def test_revoked_service_is_rejected_before_source_or_policy_resolution(routed):
    routed.current.deny = True
    with pytest.raises(PermissionError):
        routed.build()
    assert routed.current.observed == []


@pytest.mark.parametrize("fault", ("artifact_hash", "semantic_hash"))
def test_canonical_routing_control_errors_never_become_cpu_fallback(routed, fault):
    body = deepcopy(routed.body)
    if fault == "artifact_hash":
        body["routing_policy"]["sha256"] = "sha256:" + "0" * 64
    else:
        body["routing_policy_sha256"] = "sha256:" + "0" * 64
    configuration = RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    with pytest.raises(ValueError):
        routed.build(configuration)
    assert routed.current.observed == ["CPU", "CUDA"]


@pytest.mark.parametrize("routed", ["native_default"], indirect=True)
def test_wrong_native_default_is_not_approved_merely_because_cuda_profile_is_present(routed):
    with pytest.raises(ValueError, match="NATIVE_EMBEDDING_BACKEND_SELECTION_INVALID"):
        routed.build()


def test_copied_service_identity_or_wrong_runtime_source_is_never_a_service_capture(routed):
    for fence, commit in ((Mock(), "a" * 40), (routed.fence, "b" * 40)):
        with pytest.raises(ValueError, match="LOCAL_INDEXING_ROUTED_SOURCE_MISMATCH"):
            build_routed_indexing_sources(
                routed.engine,
                routed.publisher,
                fence,
                routed.selected,
                source_commit=commit,
                settings=routed.settings,
            )
    assert routed.guard.call_count == 0 and routed.current.observed == []


@pytest.mark.parametrize("routed", ["source_policy", "wider_source_classes"], indirect=True)
def test_legitimate_but_different_source_policy_or_wider_population_is_not_a_matched_pair(routed):
    with pytest.raises(ValueError, match="LOCAL_INDEXING_ROUTED_SOURCE_MISMATCH"):
        routed.build()
    assert routed.current.observed == ["CPU", "CUDA"]


def test_pair_metadata_rejects_different_views_before_any_capacity_or_launch(routed):
    pair = routed.build().namespaces[0]
    cpu = copy(pair.cpu)
    cpu.owner = copy(pair.cpu.owner)
    registry = cpu.owner.configuration.registry
    cpu.owner.configuration = replace(
        cpu.owner.configuration,
        registry=replace(
            registry, namespace=registry.namespace.model_copy(update={"view": "CONCRETE_FACETS"})
        ),
    )
    with pytest.raises(ValueError, match="LOCAL_INDEXING_ROUTED_SOURCE_MISMATCH"):
        PairedIndexingNamespacePreparation(cpu, pair.cuda)
