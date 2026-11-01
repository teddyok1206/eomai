"""Private parent metadata closure only; no source permission, model or GPU execution."""

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from eom_catalog_contracts.private_chat_query_prepare import private_chat_query_context_request_id
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityRequestV2
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.embedding_batch_plan import EmbeddingBatchPlanRequest
from eom_workflow.embedding_batch_plan_family import (
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    parse_public_embedding_batch_plan_request,
)
from eom_workflow.embedding_batch_plan_v17 import (
    BATCH_PLAN_V17_PROTOCOL,
    BATCH_PLAN_V17_SCHEMA_SHA256,
    BATCH_SELECTION_V17_SCHEMA_REF,
    EmbeddingBatchPlanRequestV17,
    EmbeddingBatchSelectionV17,
    embedding_batch_private_query_plan_schema,
    private_chat_batch_parent_request_sha256,
    validate_private_batch_query_context,
    validate_private_query_batch_controls,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow.private_chat_query_execution_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member
from tests.unit.test_embedding_device_routing import allocation_document
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_source import source_case
from tests.unit.test_registered_public_query_batch_plan import registered_public_parent_case


@lru_cache(maxsize=1)
def private_parent_case():
    previous = registered_public_parent_case()
    chat = source_case(question=TEXT)
    origin = chat.execution.materialize_live_private_query(chat.ticket).origin
    route = previous.policy.model_dump(mode="json") | {"purpose": "PRIVATE_CHAT_QUERY"}
    for device in ("cpu", "cuda"):
        route[device]["backend"]["purpose"] = "PRIVATE_CHAT_QUERY"
        profile = route[device]["profile"]
        profile["resource_profile"] = seal(
            profile["resource_profile"] | {"timeout_seconds": 180}, "resource_profile_sha256"
        )
    routing = EmbeddingDeviceRoutingPolicy.model_validate(seal(route, "policy_sha256"))
    pair = previous.selection.index_pairs[0]
    policies = []
    for device, profile, view in (
        ("CPU", routing.cpu.profile, pair.cpu),
        ("CUDA", routing.cuda.profile, pair.cuda),
    ):
        template = execution_case(device)[1]
        policy = PrivateChatQueryExecutionPolicyV2.model_validate(
            seal(
                template.model_dump(mode="json")
                | {
                    "spaces": view.index.spaces.model_dump(mode="json"),
                    "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                    "resource_profile": profile.resource_profile.model_dump(mode="json"),
                },
                "policy_sha256",
            )
        )
        policies.append(policy)
    cpu, cuda = policies
    pins = {
        key: dict(
            member=member(
                "policy.json", PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF, policy, seed
            ).model_dump(mode="json")
            | {"sha256": sha256_bytes(canonical_json_bytes(policy))},
            policy_sha256=policy.policy_sha256,
        )
        for key, policy, seed in (("cpu", cpu, "c"), ("cuda", cuda, "d"))
    }
    old = previous.selection
    scope = seal(old.scope.model_dump(mode="json") | {"actor_id": origin.actor_id}, "scope_sha256")
    selection = EmbeddingBatchSelectionV17.model_validate(
        seal(
            dict(
                schema_version=BATCH_PLAN_V17_PROTOCOL,
                message_type="SELECTION",
                purpose="PRIVATE_CHAT_QUERY",
                scope=scope,
                corpus_id=old.corpus_id,
                graph_snapshot=old.graph_snapshot.model_dump(mode="json"),
                access_policy_revision_id=old.access_policy_revision_id,
                origin=origin.model_dump(mode="json"),
                recipe=old.recipe.model_dump(mode="json"),
                views=["CONCRETE_FACETS"],
                source_classes=list(old.source_classes),
                query=dict(
                    consumer_purpose="GENERAL_CHAT_READ",
                    context_request_id=private_chat_query_context_request_id(origin),
                    maximum_sources=16384,
                    top_k=64,
                ),
                index_pair=pair.model_dump(mode="json"),
                private_policies=pins,
            ),
            "selection_sha256",
        )
    )
    return NS(
        previous=previous,
        selection=selection,
        request=parent_request(selection, routing),
        routing=routing,
        cpu=cpu,
        cuda=cuda,
    )


def parent_request(selection, routing):
    return EmbeddingBatchPlanRequestV17.model_validate(
        seal(
            dict(
                schema_version=BATCH_PLAN_V17_PROTOCOL,
                message_type="REQUEST",
                purpose="PRIVATE_CHAT_QUERY",
                batch_id="embeddingbatch_" + "9" * 32,
                parent_request_sha256=private_chat_batch_parent_request_sha256(selection),
                scope=selection.scope.model_dump(mode="json"),
                selection_manifest=member(
                    "selection.json", BATCH_SELECTION_V17_SCHEMA_REF, selection, "e"
                ).model_dump(mode="json"),
                selection_sha256=selection.selection_sha256,
                routing_policy=member(
                    "policy.json",
                    "eom://schemas/workflow/embedding-device-routing/1.0",
                    routing,
                    "f",
                ).model_dump(mode="json"),
                routing_policy_sha256=routing.policy_sha256,
                child_selection_sha256s=list(selection.child_selection_sha256s),
            ),
            "request_sha256",
        )
    )


def child_request(value, *, status="ACQUIRED"):
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            allocation_document(value.routing, status)
            | {"request_sha256": value.request.request_sha256},
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(value.routing, observation)
    device = decision.selected.backend.device
    pin = getattr(value.selection.private_policies, device.lower())
    policy = getattr(value, device.lower())
    template = execution_case(device)[0]
    context = PrivateChatSimilarityRequestV2.model_validate(
        seal(
            template.context_request.model_dump(mode="json")
            | dict(
                request_id=value.selection.query.context_request_id,
                query_basis=value.selection.origin.basis.model_dump(mode="json"),
                graph_snapshot=value.selection.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=value.selection.access_policy_revision_id,
                policy_sha256=value.selection.scope.access_policy_sha256,
                views=[v.model_dump(mode="json") for v in value.selection.selected_views(device)],
                source_classes=list(value.selection.source_classes),
                maximum_sources=value.selection.query.maximum_sources,
                top_k=value.selection.query.top_k,
            ),
            "request_sha256",
        )
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            template.model_dump(mode="json")
            | dict(
                context_request=context.model_dump(mode="json"),
                operator_audit=template.operator_audit.model_dump(mode="json")
                | {"operator_id": value.selection.origin.actor_id},
                native_execution_policy=pin.member.model_dump(mode="json"),
                native_execution_policy_sha256=pin.policy_sha256,
                workflow_definition_sha256=policy.workflow_definition_sha256,
                runtime_bundle=policy.runtime_bundle.model_dump(mode="json"),
                resource_profile=policy.resource_profile.model_dump(mode="json"),
            ),
            "request_sha256",
        )
    )
    return decision, request


def controls(value):
    validate_private_query_batch_controls(
        value.request, value.selection, value.routing, value.cpu, value.cuda
    )


def test_private_parent17_is_independently_pinned_and_has_no_text_or_approved_anchor():
    value = private_parent_case()
    controls(value)
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-plan-v1.7.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == BATCH_PLAN_V17_SCHEMA_SHA256
    Draft202012Validator.check_schema(embedding_batch_private_query_plan_schema())
    assert (
        TEXT not in value.selection.model_dump_json()
        and "anchors" not in type(value.selection).model_fields
    )
    assert len(value.selection.child_selection_sha256s) == 1
    assert (
        private_chat_batch_parent_request_sha256(value.selection)
        == value.request.parent_request_sha256
    )
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")
    # Shared metadata parsing is not admission through the public source owner.
    for parser, data in (
        (parse_embedding_batch_selection, value.selection),
        (parse_embedding_batch_plan_request, value.request),
    ):
        assert parser(data) == data
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_PLAN_INVALID"):
        parse_public_embedding_batch_plan_request(value.request)


@pytest.mark.parametrize("version", ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"))
def test_private_request_cannot_enter_any_previous_family_after_rehashing(version):
    value = private_parent_case()
    body = seal(
        value.request.model_dump(mode="json")
        | {"schema_version": "embedding-batch-plan/" + version},
        "request_sha256",
    )
    with pytest.raises(ValueError):
        parse_embedding_batch_plan_request(body)


@pytest.mark.parametrize("status", ("ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"))
def test_private_child_uses_only_the_original_question_and_actual_selected_device(status):
    value = private_parent_case()
    decision, child = child_request(value, status=status)
    validate_private_batch_query_context(value.request, value.selection, decision, 0, child)
    assert child.context_request.query_basis == value.selection.origin.basis
    assert child.resource_profile.device == ("CUDA" if status == "ACQUIRED" else "CPU")
    assert len(value.request.child_selection_sha256s) == 1


@pytest.mark.parametrize("field", ("text", "path", "actor_role", "password", "anchors", "runtime"))
def test_private_selection_cannot_supply_text_authority_or_approved_item_impersonation(field):
    body = private_parent_case().selection.model_dump(mode="json") | {
        field: "PRIVATE_DO_NOT_DISCLOSE"
    }
    with pytest.raises(ValueError) as error:
        EmbeddingBatchSelectionV17.model_validate(seal(body, "selection_sha256"))
    assert "PRIVATE_DO_NOT_DISCLOSE" not in str(error.value)


@pytest.mark.parametrize(
    "fault", ("actor", "context", "classes", "device", "gpu_missing", "legacy_policy", "hash")
)
def test_ambiguous_or_mutated_private_selection_never_names_work(fault):
    body = private_parent_case().selection.model_dump(mode="json")
    if fault == "actor":
        body["scope"] = seal(body["scope"] | {"actor_id": "operator_" + "f" * 32}, "scope_sha256")
    elif fault == "context":
        body["query"]["context_request_id"] = "similarityrequest_" + "f" * 32
    elif fault == "classes":
        body["source_classes"] *= 2
    elif fault == "device":
        pair = body["index_pair"]
        pair["cpu"], pair["cuda"] = pair["cuda"], pair["cpu"]
    elif fault == "gpu_missing":
        body["index_pair"]["cuda"]["index"] = None
    elif fault == "legacy_policy":
        body["private_policies"]["cpu"]["member"]["schema_ref"] = (
            "eom://schemas/workflow/reference-query-execution-policy/1.0"
        )
    body = seal(body, "selection_sha256")
    if fault == "hash":
        body["selection_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV17.model_validate(body)


def test_missing_cpu_index_does_not_block_valid_gpu_or_invent_a_fallback_index():
    original = private_parent_case()
    body = original.selection.model_dump(mode="json")
    body["index_pair"]["cpu"]["index"] = None
    selection = EmbeddingBatchSelectionV17.model_validate(seal(body, "selection_sha256"))
    value = NS(
        **(
            vars(original)
            | {"selection": selection, "request": parent_request(selection, original.routing)}
        )
    )
    controls(value)
    decision, child = child_request(value)
    validate_private_batch_query_context(value.request, selection, decision, 0, child)
    assert selection.index_pair.cpu.index is None
    with pytest.raises(ValueError):
        child_request(value, status="BUSY")


@pytest.mark.parametrize("fault", ("parent", "selection", "route", "child", "member"))
def test_rehashed_parent_cannot_borrow_another_selection_or_policy(fault):
    original = private_parent_case()
    body = original.request.model_dump(mode="json")
    field = {
        "parent": "parent_request_sha256",
        "selection": "selection_sha256",
        "route": "routing_policy_sha256",
    }.get(fault)
    if field:
        body[field] = "sha256:" + "f" * 64
    elif fault == "child":
        body["child_selection_sha256s"] = ["sha256:" + "f" * 64]
    else:
        body["selection_manifest"]["sha256"] = "sha256:" + "f" * 64
    request = EmbeddingBatchPlanRequestV17.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        controls(NS(**(vars(original) | {"request": request})))


@pytest.mark.parametrize("ordinal", (True, -1, 1, 0.0))
def test_exactly_one_child_never_uses_an_invalid_ordinal(ordinal):
    value = private_parent_case()
    decision, child = child_request(value)
    with pytest.raises(ValueError):
        validate_private_batch_query_context(
            value.request, value.selection, decision, ordinal, child
        )


def test_old_public_request_and_other_route_cannot_reuse_a_private_question():
    value = private_parent_case()
    decision, child = child_request(value)
    wrong = seal(
        decision.model_dump(mode="json") | {"request_sha256": "sha256:" + "f" * 64},
        "decision_sha256",
    )
    with pytest.raises(ValueError):
        validate_private_batch_query_context(value.request, value.selection, wrong, 0, child)
    with pytest.raises(ValueError):
        EmbeddingBatchPlanRequest.model_validate(value.request)


def test_constructed_metadata_and_second_child_are_revalidated():
    value = private_parent_case()
    with pytest.raises(ValueError):
        private_chat_batch_parent_request_sha256(
            value.selection.model_copy(update={"selection_sha256": "sha256:" + "f" * 64})
        )
    body = value.request.model_dump(mode="json")
    body["child_selection_sha256s"] *= 2
    with pytest.raises(ValueError):
        EmbeddingBatchPlanRequestV17.model_validate(seal(body, "request_sha256"))


@pytest.mark.parametrize(
    "fault", ("basis", "actor", "policy", "graph", "context", "limit", "index", "native_policy")
)
def test_valid_but_different_private_child_is_not_a_member_of_the_parent(fault):
    value = private_parent_case()
    decision, child = child_request(value)
    body = child.model_dump(mode="json")
    context = body["context_request"]
    if fault == "basis":
        context["query_basis"] = seal(
            context["query_basis"] | {"turn_id": "chatturn_" + "f" * 32}, "basis_sha256"
        )
    elif fault == "actor":
        body["operator_audit"]["operator_id"] = "operator_" + "f" * 32
    elif fault == "policy":
        context["policy_sha256"] = "sha256:" + "f" * 64
    elif fault == "graph":
        context["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    elif fault == "context":
        context["request_id"] = "similarityrequest_" + "f" * 32
    elif fault == "limit":
        context["maximum_sources"] -= 1
    elif fault == "index":
        context["views"][0]["index"]["index_revision_id"] = "embeddingindexrev_" + "f" * 32
    else:
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    body["context_request"] = seal(context, "request_sha256")
    altered = PrivateChatQueryWorkflowRequestV2.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        validate_private_batch_query_context(value.request, value.selection, decision, 0, altered)


@pytest.mark.parametrize("device", ("cpu", "cuda"))
@pytest.mark.parametrize("reseal_selection", (False, True))
def test_independently_resealed_private_policy_cannot_change_the_selected_runtime(
    device, reseal_selection
):
    original = private_parent_case()
    body = getattr(original, device).model_dump(mode="json")
    body["resource_profile"] = seal(
        body["resource_profile"] | {"timeout_seconds": 179}, "resource_profile_sha256"
    )
    policy = PrivateChatQueryExecutionPolicyV2.model_validate(seal(body, "policy_sha256"))
    value = NS(**(vars(original) | {device: policy}))
    if reseal_selection:
        selected = original.selection.model_dump(mode="json")
        selected["private_policies"][device].update(
            member=member(
                "policy.json",
                PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
                policy,
                "7" if device == "cpu" else "8",
            )
            .model_copy(update={"sha256": sha256_bytes(canonical_json_bytes(policy))})
            .model_dump(mode="json"),
            policy_sha256=policy.policy_sha256,
        )
        value.selection = EmbeddingBatchSelectionV17.model_validate(
            seal(selected, "selection_sha256")
        )
        value.request = parent_request(value.selection, value.routing)
    with pytest.raises(ValueError):
        controls(value)


def test_parent_control_hashes_match_the_existing_actual_publication_serializers(tmp_path):
    from eom_orchestrator.local_embedding_control_artifacts import (
        LocalEmbeddingControlArtifactPublisher,
    )

    from tests.unit.test_control_file_set_publication import _publisher
    from tests.unit.test_local_embedding_control_artifacts import NOW

    value = private_parent_case()
    publisher, _ = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls_owner = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    for device in ("cpu", "cuda"):
        published = controls_owner.publish_private_chat_public_query_policy(
            getattr(value, device), idempotency_key="private-parent17:" + device, created_at=NOW
        )
        assert (
            published.member.sha256
            == getattr(value.selection.private_policies, device).member.sha256
        )
    route = controls_owner.publish_device_routing_policy(
        value.routing, idempotency_key="private-parent17:routing"
    )
    assert route.member.sha256 == value.request.routing_policy.sha256
    controls(value)


def test_private_policies_cannot_claim_two_hashes_for_one_immutable_member():
    body = private_parent_case().selection.model_dump(mode="json")
    cpu = body["private_policies"]["cpu"]["member"]
    body["private_policies"]["cuda"]["member"].update(
        artifact_id=cpu["artifact_id"], artifact_revision_id=cpu["artifact_revision_id"]
    )
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV17.model_validate(seal(body, "selection_sha256"))


def test_private_selection_publication_resolves_exact_artifact_and_replays_without_new_job(
    tmp_path,
):
    from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
    from eom_catalog_service.settings import CatalogSettings
    from eom_orchestrator.local_embedding_control_artifacts import (
        BATCH_SELECTION_ARTIFACT_TYPE,
        LocalEmbeddingControlArtifactPublisher,
    )
    from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
    from sqlalchemy import func, select

    from tests.unit.test_control_file_set_publication import _publisher

    selection = private_parent_case().selection
    publisher, _ = _publisher(tmp_path)
    workspace = tmp_path / "private-controls"
    workspace.mkdir()
    publisher.settings = replace(publisher.settings, workspace_root=workspace)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    key = "private-parent17:selection"
    first = adapter.publish_private_chat_batch_selection(selection, idempotency_key=key)
    assert adapter.publish_private_chat_batch_selection(selection, idempotency_key=key) == first
    assert first.semantic_sha256 == selection.selection_sha256
    pointer = first.member
    assert pointer.member_path == "selection.json"
    assert pointer.schema_ref == BATCH_SELECTION_V17_SCHEMA_REF
    assert pointer.sha256 == sha256_bytes(canonical_json_bytes(selection.model_dump(mode="json")))
    assert not tuple(workspace.iterdir())
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        member = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(BATCH_SELECTION_ARTIFACT_TYPE,),
            expected_primary_file="selection.json",
            max_bytes=64 * 1024**2,
        )
        assert EmbeddingBatchSelectionV17.model_validate_json(member.payload) == selection
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
        job = session.get(JobRecord, first.owner_job_id)
        assert job is not None
        metadata = canonical_json_bytes(job.request)
        assert b'"origin"' not in metadata and b'"index_pair"' not in metadata
        assert TEXT.encode() not in member.payload and TEXT.encode() not in metadata


@pytest.mark.parametrize("fault", ("hash", "family", "changed_selection", "same_key_other_kind"))
def test_private_selection_publication_rejects_invalid_or_conflicting_replay(tmp_path, fault):
    from eom_orchestrator.control_service import ControlPlaneError
    from eom_orchestrator.local_embedding_control_artifacts import (
        LocalEmbeddingControlArtifactPublisher,
    )
    from eom_orchestrator.models import JobRecord
    from sqlalchemy import func, select

    from tests.unit.test_control_file_set_publication import _publisher

    value = private_parent_case()
    publisher, _ = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    key = "private-parent17:selection"
    selection = value.selection
    if fault == "hash":
        invalid = selection.model_copy(update={"selection_sha256": "sha256:" + "f" * 64})
        with pytest.raises(ValueError):
            adapter.publish_private_chat_batch_selection(invalid, idempotency_key=key)
    elif fault == "family":
        with pytest.raises(ValueError):
            adapter.publish_private_chat_batch_selection(
                value.previous.selection, idempotency_key=key
            )
    else:
        first = adapter.publish_private_chat_batch_selection(selection, idempotency_key=key)
        with pytest.raises(ControlPlaneError) as error:
            if fault == "same_key_other_kind":
                adapter.publish_device_routing_policy(value.routing, idempotency_key=key)
            else:
                body = selection.model_dump(mode="json")
                body["query"]["top_k"] -= 1
                changed = EmbeddingBatchSelectionV17.model_validate(seal(body, "selection_sha256"))
                adapter.publish_private_chat_batch_selection(changed, idempotency_key=key)
        assert error.value.code == "CONTROL_FILE_SET_CONFLICT"
        assert adapter.publish_private_chat_batch_selection(selection, idempotency_key=key) == first
    with publisher.sessions() as session:
        expected = 0 if fault in {"hash", "family"} else 1
        assert session.scalar(select(func.count()).select_from(JobRecord)) == expected
