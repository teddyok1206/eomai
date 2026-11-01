"""Real controls/ORM roots and Chat bytes; declared IAM/public DOCUMENT seams, no GPU."""

from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.private_chat_query_prepare import private_chat_query_context_request_id
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.public_solution_similarity_read import CatalogPublicSolutionSimilarityRead
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.embedding_runtime_bundle_artifacts import (
    EmbeddingRuntimeBundleArtifactPublisher,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import JobRecord
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.embedding_batch_plan_v17 import (
    EmbeddingBatchPlanRequestV17,
    EmbeddingBatchSelectionV17,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryExecutionPolicyV2
from eom_workflow_runner import private_chat_query_preparation as preparation
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.embedding_batch_plan_admission import EmbeddingBatchPlanOwnerConfiguration
from eom_workflow_runner.private_chat_batch_plan_admission import (
    CatalogPrivateChatBatchPlanAdmission,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    PrivateChatQueryOwnerConfiguration,
)
from sqlalchemy import func, select, update

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_public_similarity_service import private_public_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_batch_plan import parent_request, private_parent_case
from tests.unit.test_private_chat_query_source import source_case


def make_private_batch_admission_case(
    tmp_path,
    monkeypatch,
    *,
    cpu_index=True,
    publisher=None,
    key="synthetic-private-parent",
    identity_seed=None,
):
    if publisher is None:
        publisher, _ = _publisher(tmp_path)
        publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    original = private_parent_case()
    chat = source_case(question=TEXT, identity_seed=identity_seed)
    origin = chat.execution.materialize_live_private_query(chat.ticket).origin
    if identity_seed is None:
        assert origin == original.selection.origin
    settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    bundles, policies, saved_policies = {}, {}, {}
    for device in ("CPU", "CUDA"):
        bundle_body = execution_case(device)[2].model_dump(mode="json")
        if device == "CUDA":
            # Independent CPU/CUDA fixtures use one model revision ID. An actual
            # paired bundle must distinguish its differing runtime manifest.
            bundle_body["execution_model_spec"] = seal(
                bundle_body["execution_model_spec"]
                | {"model_revision_id": "embeddingmodelrev_" + "f" * 32},
                "manifest_sha256",
            )
        bundle = EmbeddingRuntimeBundle.model_validate(
            seal(
                bundle_body
                | {
                    "bundle_revision_id": "embeddingbundlerev_"
                    + content_sha256({"key": key, "device": device})[7:39]
                },
                "bundle_sha256",
            )
        )
        saved_bundle = EmbeddingRuntimeBundleArtifactPublisher(
            ControlArtifactPublisher(publisher.engine, publisher.settings), source_commit="a" * 40
        ).publish(bundle, created_at=NOW)
        spaces = execution_case(device)[1].spaces.model_dump(mode="json")
        for name in ("query", "document"):
            spaces[name] = seal(
                spaces[name] | {"model_spec": bundle.execution_model_spec.model_dump(mode="json")},
                "space_sha256",
            )
        policy = PrivateChatQueryExecutionPolicyV2.model_validate(
            seal(
                execution_case(device)[1].model_dump(mode="json")
                | {
                    "runtime_bundle": saved_bundle.bundle.model_dump(mode="json"),
                    "spaces": spaces,
                    "resource_profile": getattr(
                        original, device.lower()
                    ).resource_profile.model_dump(mode="json"),
                },
                "policy_sha256",
            )
        )
        bundles[device], policies[device] = saved_bundle.bundle, policy
        saved_policies[device] = controls.publish_private_chat_public_query_policy(
            policy, idempotency_key=key + ":policy:" + device, created_at=NOW
        )
    route_body = original.routing.model_dump(mode="json")
    for device in ("CPU", "CUDA"):
        route_body[device.lower()]["profile"]["runtime_bundle"] = bundles[device].model_dump(
            mode="json"
        )
        route_body[device.lower()]["profile"]["space"] = policies[
            device
        ].spaces.document.model_dump(mode="json")
    routing = EmbeddingDeviceRoutingPolicy.model_validate(seal(route_body, "policy_sha256"))
    saved_routing = controls.publish_device_routing_policy(
        routing, idempotency_key=key + ":routing"
    )
    selection_body = original.selection.model_dump(mode="json")
    selection_body["origin"] = origin.model_dump(mode="json")
    selection_body["query"]["context_request_id"] = private_chat_query_context_request_id(origin)
    for device in ("CPU", "CUDA"):
        selection_body["index_pair"][device.lower()]["index"]["spaces"] = policies[
            device
        ].spaces.model_dump(mode="json")
        selection_body["private_policies"][device.lower()] = dict(
            member=saved_policies[device].member.model_dump(mode="json"),
            policy_sha256=policies[device].policy_sha256,
        )
    if not cpu_index:
        selection_body["index_pair"]["cpu"]["index"] = None
    selection = EmbeddingBatchSelectionV17.model_validate(seal(selection_body, "selection_sha256"))
    saved_selection = controls.publish_private_chat_batch_selection(
        selection, idempotency_key=key + ":selection"
    )
    request = EmbeddingBatchPlanRequestV17.model_validate(
        seal(
            parent_request(selection, routing).model_dump(mode="json")
            | dict(
                selection_manifest=saved_selection.member.model_dump(mode="json"),
                routing_policy=saved_routing.member.model_dump(mode="json"),
                batch_id="embeddingbatch_" + content_sha256({"key": key})[7:39],
            ),
            "request_sha256",
        )
    )
    fault = NS(value=None)
    events = []

    def identity(_session, actor):
        assert actor == origin.actor_id
        events.append("identity")
        if fault.value == "identity":
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    owners = {}
    for device in ("CPU", "CUDA"):
        policy = policies[device]
        sources = CatalogPrivateChatQuerySourceOwner(
            publisher.engine,
            PrivateChatQueryOwnerConfiguration(
                EmbeddingRegistryOwnerConfiguration(
                    selection.corpus_id,
                    PublicSolutionIndexNamespace(
                        storage_partition="public-solution",
                        space_sha256=policy.spaces.document.space_sha256,
                        view="CONCRETE_FACETS",
                        recipe_sha256=selection.recipe.recipe_sha256,
                    ),
                    policy.spaces.document,
                    selection.recipe,
                    selection.source_classes,
                ),
                saved_policies[device].member,
                policy.policy_sha256,
                bundles[device],
            ),
            chat=NS(
                materialize=chat.execution.materialize_live_private_query,
                authorize=chat.execution.authorize_live_private_query,
            ),
            identity_fence=NS(fence_current_operator=identity),
            settings=settings,
        )
        owners[device] = CatalogPrivateChatQueryOwnerAdmission(sources)

    def documents(application, session, caller, context):
        assert session.get_bind() is publisher.engine
        assert caller.operator_id == origin.actor_id
        device = context.views[0].index.spaces.document.runtime.device
        assert application.catalog is owners[device].catalog
        assert context.graph_snapshot == selection.graph_snapshot
        assert context.query_basis == origin.basis
        events.append("documents:" + device)
        if fault.value == "public":
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return replace(
            private_public_case()[1],
            space=policies[device].spaces.document,
            recipe=selection.recipe,
        ), object()

    monkeypatch.setattr(
        CatalogPublicSolutionSimilarityRead, "read_private_documents_in_session", documents
    )
    monkeypatch.setattr(
        preparation, "effective_permissions", lambda *_: frozenset({PermissionKey.WORKFLOW_START})
    )
    configuration = EmbeddingBatchPlanOwnerConfiguration(
        EmbeddingRegistryLookup(
            selection.corpus_id,
            owners["CPU"].configuration.registry.namespace,
            selection.graph_snapshot,
            selection.access_policy_revision_id,
            selection.scope.access_policy_sha256,
            selection.query.maximum_sources,
        ),
        saved_routing.member,
        routing.policy_sha256,
    )
    owner = CatalogPrivateChatBatchPlanAdmission(
        owners["CPU"], owners["CUDA"], EmbeddingRegistryCaller(origin.actor_id), configuration
    )
    return NS(**locals())


@pytest.fixture(params=(True, False))
def admitted(tmp_path, monkeypatch, request):
    return make_private_batch_admission_case(tmp_path, monkeypatch, cpu_index=request.param)


def test_private_parent_uses_actual_owned_question_and_controls_without_creating_work(admitted):
    value = admitted
    operation = CatalogEmbeddingBatchExecution(
        value.owner, value.publisher, source_commit="a" * 40, controller_release="b" * 40
    )
    assert operation.admission is value.owner
    with value.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
        with value.owner.admit(session, value.request) as resolved:
            assert resolved.selection == value.selection and resolved.policy == value.routing
            assert TEXT not in repr(resolved)
            assert session.scalar(select(func.count()).select_from(JobRecord)) == before
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
        assert value.events.count("documents:CUDA") == 4
        assert value.events.count("documents:CPU") == (4 if value.cpu_index else 0)
        for job in session.scalars(select(JobRecord)):
            assert TEXT.encode() not in canonical_json_bytes(job.request)
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


@pytest.mark.parametrize("fault", ("identity", "chat", "public", "cpu_policy"))
def test_late_private_or_public_denial_rolls_back_original_caller_changes(admitted, fault):
    value = admitted
    with (
        pytest.raises((ValueError, OperatorAuthorizationFenceError)),
        value.publisher.sessions.begin() as session,
        value.owner.admit(session, value.request),
    ):
        session.execute(
            update(JobRecord)
            .where(JobRecord.job_id == value.saved_selection.owner_job_id)
            .values(error_message="synthetic-parent-write")
            .execution_options(synchronize_session=False)
        )
        value.fault.value = fault
        if fault == "chat":
            value.chat.repository.revoked = True
        if fault == "cpu_policy":
            session.execute(
                update(JobRecord)
                .where(JobRecord.job_id == value.saved_policies["CPU"].owner_job_id)
                .values(status="FAILED")
                .execution_options(synchronize_session=False)
            )
    with value.publisher.sessions() as session:
        assert session.get(JobRecord, value.saved_selection.owner_job_id).error_message is None
        assert (
            session.get(JobRecord, value.saved_policies["CPU"].owner_job_id).status == "SUCCEEDED"
        )


def test_public_parent_never_enters_private_source_owner(admitted):
    value = admitted
    with (
        pytest.raises(ValueError, match="PRIVATE_CHAT_BATCH_PLAN_ADMISSION_INVALID"),
        value.publisher.sessions.begin() as session,
        value.owner.admit(session, planning_case().request),
    ):
        raise AssertionError("public request cannot acquire private source authority")
    assert value.events == []


def test_foreign_actor_denied_before_private_materialization(admitted):
    value = admitted
    owner = CatalogPrivateChatBatchPlanAdmission(
        value.owners["CPU"],
        value.owners["CUDA"],
        EmbeddingRegistryCaller("operator_" + "f" * 32),
        value.configuration,
    )
    with (
        pytest.raises(ValueError, match="PRIVATE_CHAT_BATCH_PLAN_ADMISSION_INVALID"),
        value.publisher.sessions.begin() as session,
        owner.admit(session, value.request),
    ):
        raise AssertionError("foreign operator cannot read the question")
    assert value.events == []


@pytest.mark.parametrize("pointer", ("selection_manifest", "routing_policy"))
def test_wrong_pinned_control_hash_never_materializes_the_private_question(admitted, pointer):
    value = admitted
    body = value.request.model_dump(mode="json")
    body[pointer]["sha256"] = "sha256:" + "f" * 64
    request = EmbeddingBatchPlanRequestV17.model_validate(seal(body, "request_sha256"))
    with (
        pytest.raises(ValueError),
        value.publisher.sessions.begin() as session,
        value.owner.admit(session, request),
    ):
        raise AssertionError("a changed control pointer is not a current source")
    assert not any(event.startswith("documents:") for event in value.events)


def test_nested_root_cannot_supply_private_parent_authority(admitted):
    value = admitted
    with (
        pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"),
        value.publisher.sessions.begin() as session,
        session.begin_nested(),
        value.owner.admit(session, value.request),
    ):
        raise AssertionError("private admission requires the original root")
    assert value.events == []
