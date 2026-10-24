"""Real local Artifact resolution; explicit synthetic IAM/source leaves, no GPU or live grant."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryOwnerConfiguration,
    EmbeddingRegistryServiceCaller,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import LocalIndexingServiceReference
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchPlanRequest,
    EmbeddingBatchSelection,
    RegisteredReviewBatchAnchor,
)
from eom_workflow_runner.embedding_batch_plan_admission import (
    CatalogEmbeddingBatchPlanAdmission,
    EmbeddingBatchPlanOwnerConfiguration,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_registered_review_embedding_delta import _entry

SELECTION_KEY = "synthetic-batch-selection"
POLICY_KEY = "synthetic-batch-policy"


def source_case(
    tmp_path,
    monkeypatch,
    *,
    purpose="REFERENCE_QUERY",
    service=False,
    mixed=False,
    publisher=None,
    key="synthetic",
    planned=None,
):
    case = planned or planning_case(purpose=purpose)
    entries = tuple(embedding_entry(seed) for seed in ("a", "b"))[: len(case.selection.anchors)]
    body = case.selection.model_dump(mode="json")
    if service:
        caller = EmbeddingRegistryServiceCaller(
            LocalIndexingServiceReference(
                service_id="localindexservice_" + "1" * 32,
                service_revision_id="localindexservicerev_" + "1" * 32,
                service_identity_sha256="sha256:" + "1" * 64,
            )
        )
        body["scope"].update(
            actor_kind="LOCAL_INDEXING_SERVICE", actor_id=caller.service.service_id
        )
    else:
        caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
        body["scope"]["actor_id"] = caller.operator_id
    body["scope"] = seal(body["scope"], "scope_sha256")
    if mixed:
        entry = _entry()
        entries = (entries[0], entry)
        body["anchors"][1] = {
            "basis": "REGISTERED_ITEM_REVIEW",
            "source": entry.profile.source_basis.source.model_dump(mode="json"),
            "profile": RegisteredReviewProfilePointer.from_profile(entry.profile).model_dump(
                mode="json"
            ),
            "review_evidence": entry.profile.source_basis.review_evidence.model_dump(mode="json"),
        }
        # Both synthetic source families must retain the one selected Graph.
        legacy = entries[0]
        assert (
            legacy.profile.source_basis.graph_snapshot == entry.profile.source_basis.graph_snapshot
        )
    selection = EmbeddingBatchSelection.model_validate(seal(body, "selection_sha256"))
    if publisher is None:
        publisher, engine = _publisher(tmp_path)
    else:
        engine = publisher.engine
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    selection_key, policy_key = SELECTION_KEY + ":" + key, POLICY_KEY + ":" + key
    saved_selection = controls.publish_batch_selection(selection, idempotency_key=selection_key)
    saved_policy = controls.publish_device_routing_policy(case.policy, idempotency_key=policy_key)
    request = EmbeddingBatchPlanRequest.model_validate(
        seal(
            case.request.model_dump(mode="json")
            | {
                "scope": selection.scope.model_dump(mode="json"),
                "selection_manifest": saved_selection.member.model_dump(mode="json"),
                "selection_sha256": selection.selection_sha256,
                "routing_policy": saved_policy.member.model_dump(mode="json"),
                "routing_policy_sha256": case.policy.policy_sha256,
                "child_selection_sha256s": list(selection.child_selection_sha256s),
            },
            "request_sha256",
        )
    )
    namespace = EmbeddingIndexNamespace(
        storage_partition=selection.scope.storage_partition,
        space_sha256=case.policy.cpu.profile.space.space_sha256,
        view="CONTENT_ONLY",
        recipe_sha256=selection.recipe.recipe_sha256,
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    registry = EmbeddingRegistryOwnerConfiguration(
        selection.corpus_id,
        namespace,
        case.policy.cpu.profile.space,
        selection.recipe,
        ("APPROVED_ITEM", "PAST_EXAM"),
    )
    catalog = CatalogEmbeddingRegistryVerifier(
        engine,
        registry,
        identity_fence=Mock(),
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    scope = EmbeddingRegistryLookup(
        selection.corpus_id,
        namespace,
        selection.graph_snapshot,
        selection.access_policy_revision_id,
        selection.scope.access_policy_sha256,
        1024,
    )
    current = ResolvedEmbeddingLookup(
        selection.corpus_id,
        registry.space,
        registry.recipe,
        tuple(entry.profile.source_basis.source for entry in entries),
        entries,
    )
    value = SimpleNamespace(
        case=case,
        request=request,
        selection=selection,
        controls=controls,
        publisher=publisher,
        engine=engine,
        current=current,
        catalog=catalog,
        caller=caller,
        scope=scope,
        saved_selection=saved_selection,
        saved_policy=saved_policy,
        selection_key=selection_key,
        policy_key=policy_key,
        calls=[],
        denied=False,
    )

    def fence(session, actual, lookup):
        assert actual is caller and lookup == scope
        value.calls.append(("scope", session))
        if value.denied:
            raise ValueError("SYNTHETIC_CURRENT_AUTHORITY_DENIED")

    def resolve(session, actual, selected):
        assert actual is caller and selected.scope == scope
        assert selected.source_revision_ids == tuple(
            sorted(anchor.source.item_revision_id for anchor in selection.anchors)
        )
        fence(session, actual, selected.scope)
        value.calls.append(("sources", session))
        return value.current

    monkeypatch.setattr(catalog, "authorize_scope", fence)
    monkeypatch.setattr(catalog, "resolve_selected_sources", resolve)
    value.owner = CatalogEmbeddingBatchPlanAdmission(
        catalog,
        caller,
        EmbeddingBatchPlanOwnerConfiguration(scope, saved_policy.member, case.policy.policy_sha256),
    )
    return value


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    value = source_case(tmp_path, monkeypatch)
    yield value
    value.engine.dispose()


def test_canonical_publication_replay_and_current_source_window(admitted):
    value = admitted
    assert (
        value.controls.publish_batch_selection(value.selection, idempotency_key=value.selection_key)
        == value.saved_selection
    )
    assert (
        value.controls.publish_device_routing_policy(
            value.case.policy, idempotency_key=value.policy_key
        )
        == value.saved_policy
    )
    assert value.saved_selection.member.sha256 != value.selection.selection_sha256
    assert value.saved_policy.member.sha256 != value.case.policy.policy_sha256
    with value.publisher.sessions() as session, session.begin():
        with value.owner.admit(session, value.request) as resolved:
            assert resolved.selection == value.selection
            assert resolved.policy == value.case.policy
            assert resolved.sources is value.current
            assert [kind for kind, _ in value.calls].count("sources") == 1
        assert [kind for kind, _ in value.calls].count("sources") == 2
        assert all(current is session for _, current in value.calls)
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        for job in session.scalars(select(JobRecord)):
            raw = canonical_json_bytes(job.request)
            assert len(raw) < 4096 and b'"anchors"' not in raw and b'"rows"' not in raw


def test_publication_cannot_switch_kind_or_forge_hash(admitted):
    value = admitted
    with pytest.raises(ControlPlaneError):
        value.controls.publish_device_routing_policy(
            value.case.policy, idempotency_key=value.selection_key
        )
    with pytest.raises(ValueError):
        value.controls.publish_batch_selection(
            value.selection.model_copy(update={"selection_sha256": "sha256:" + "f" * 64}),
            idempotency_key="invalid-selection",
        )


@pytest.mark.parametrize("fault", ("scope", "actor", "profile", "raw", "producer", "truncated"))
def test_wrong_or_unresolved_pins_never_enter_admission_body(admitted, fault):
    value = admitted
    request = value.request
    if fault in {"scope", "actor"}:
        scope = request.scope.model_dump(mode="json")
        scope["storage_partition" if fault == "scope" else "actor_id"] = (
            "other-partition" if fault == "scope" else "operator_" + "f" * 32
        )
        request = EmbeddingBatchPlanRequest.model_validate(
            seal(
                request.model_dump(mode="json") | {"scope": seal(scope, "scope_sha256")},
                "request_sha256",
            )
        )
    elif fault == "profile":
        value.current = replace(value.current, entries=())
    elif fault == "raw":
        pointer = request.selection_manifest.model_dump(mode="json") | {
            "sha256": "sha256:" + "f" * 64
        }
        request = EmbeddingBatchPlanRequest.model_validate(
            seal(
                request.model_dump(mode="json") | {"selection_manifest": pointer}, "request_sha256"
            )
        )
    elif fault == "producer":
        with value.publisher.sessions() as session, session.begin():
            session.get(JobRecord, value.saved_selection.owner_job_id).status = "FAILED"
    else:
        value.current = replace(value.current, truncated=True)
    with (
        pytest.raises(ValueError),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit(session, request),
    ):
        pytest.fail("invalid source reached parent admission")


def test_scope_denial_happens_before_any_control_bytes(admitted, monkeypatch):
    value = admitted
    value.denied = True
    read = Mock(side_effect=AssertionError("must not read controls before current authority"))
    monkeypatch.setattr(value.owner, "_read_control", read)
    with (
        pytest.raises(ValueError, match="CURRENT_AUTHORITY_DENIED"),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        pytest.fail("denied actor entered source window")
    read.assert_not_called()


@pytest.mark.parametrize("fault", ("revoked", "changed_source", "producer"))
def test_late_denial_rolls_back_caller_changes(admitted, fault):
    value = admitted
    with (
        pytest.raises(ValueError),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        if fault == "revoked":
            value.denied = True
        elif fault == "changed_source":
            value.current = replace(value.current, entries=())
        else:
            session.get(JobRecord, value.saved_selection.owner_job_id).status = "FAILED"
    with value.publisher.sessions() as session:
        assert session.get(JobRecord, value.saved_selection.owner_job_id).status == "SUCCEEDED"


def test_replay_rechecks_current_authority_instead_of_using_previous_success(admitted):
    value = admitted
    with (
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        pass
    value.denied = True
    with (
        pytest.raises(ValueError, match="CURRENT_AUTHORITY_DENIED"),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        pytest.fail("past success was reused as permission")


def test_registered_review_index_uses_its_own_evidence_and_service_actor(tmp_path, monkeypatch):
    value = source_case(tmp_path, monkeypatch, purpose="INDEX", service=True, mixed=True)
    try:
        with (
            value.publisher.sessions() as session,
            session.begin(),
            value.owner.admit(session, value.request) as resolved,
        ):
            anchor = resolved.selection.anchors[1]
            assert isinstance(anchor, RegisteredReviewBatchAnchor)
            assert (
                anchor.review_evidence
                == value.current.entries[1].profile.source_basis.review_evidence
            )
            assert resolved.selection.scope.actor_id == value.caller.service.service_id
    finally:
        value.engine.dispose()


def test_registered_review_anchor_cannot_become_a_reference_query(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        source_case(tmp_path, monkeypatch, mixed=True)


def test_nested_or_replaced_transaction_is_not_an_admission_window(admitted):
    value = admitted
    with (
        value.publisher.sessions() as session,
        session.begin(),
        session.begin_nested(),
        pytest.raises(ValueError),
        value.owner.admit(session, value.request),
    ):
        pytest.fail("savepoint was treated as source root")
    with value.publisher.sessions() as session:
        session.begin()
        try:
            with pytest.raises(ValueError), value.owner.admit(session, value.request):
                session.rollback()
                session.begin()
        finally:
            session.rollback()


def test_other_installed_policy_is_rejected_even_when_candidate_is_valid(admitted):
    value = admitted
    pointer = value.saved_policy.member.model_copy(
        update={"artifact_revision_id": "rev_" + "f" * 32}
    )
    config = replace(value.owner.configuration, routing_policy=pointer)
    owner = CatalogEmbeddingBatchPlanAdmission(value.catalog, value.caller, config)
    with (
        pytest.raises(ValueError),
        value.publisher.sessions() as session,
        session.begin(),
        owner.admit(session, value.request),
    ):
        pytest.fail("request candidate activated itself")


def test_invalid_pointers_cannot_create_owner_configuration(admitted):
    config = admitted.owner.configuration
    with pytest.raises(ValueError):
        replace(
            config,
            routing_policy=config.routing_policy.model_copy(update={"member_path": "x.json"}),
        )


def test_metadata_member_lifecycle_is_checked_not_just_content_hash(admitted):
    value = admitted
    with value.publisher.sessions() as session, session.begin():
        revision = session.get(
            ArtifactRevisionRecord, value.saved_selection.member.artifact_revision_id
        )
        assert revision is not None
        revision.manifest = dict(revision.manifest) | {"content_hash": "sha256:" + "f" * 64}
    with (
        pytest.raises(ValueError),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit(session, value.request),
    ):
        pytest.fail("invalid manifest was accepted")
