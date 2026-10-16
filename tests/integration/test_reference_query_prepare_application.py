"""Actual guarded PostgreSQL application roots/replay; Identity/source/driver are synthetic.

No model, installed API capture or NAS writes. Synthetic failed/completed state
injection is confined to this disposable database and is not live acceptance.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.similarity_context_service import validate_similarity_preparation
from eom_identity_service import OperatorAuthorizationFenceError
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.reference_query_prepare_application import (
    NativeReferenceQueryPreparation,
    reference_query_prepare_identity,
)
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_submission import prepared_query as prepared_query
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_reference_query_prepare_application import query_runner, wire_request

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_startup_control_read_uses_real_read_only_root_without_any_queue_work(prepared_query):
    from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
    from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
    from eom_workflow_runner.reference_query_source_read import (
        read_selected_reference_query_controls,
    )

    value = prepared_query
    config = value.source.owner.configuration

    def counts():
        with Session(value.engine) as session:
            return tuple(
                session.scalar(select(func.count()).select_from(model))
                for model in (
                    JobRecord,
                    ArtifactRevisionRecord,
                    WorkflowInstanceRecord,
                    WorkflowCommandRecord,
                )
            )

    before = counts()
    with Session(value.engine) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        policy, bundle = read_selected_reference_query_controls(
            PinnedArtifactReadContext(session, value.source.owner.settings),
            policy_member=config.native_execution_policy,
            policy_sha256=config.native_execution_policy_sha256,
            runtime_bundle=config.runtime_bundle,
        )
        assert (
            policy == value.source.policy
            and bundle.bundle_sha256 == config.runtime_bundle.bundle_sha256
        )
    assert counts() == before and value.source.calls == []
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize("fault", ("none", "space"))
def test_owner_runtime_boot_is_read_only_and_validates_controls_before_launcher(
    prepared_query, observation, monkeypatch, tmp_path, fault
):
    """Real PG/controls/FD layout; account, installed-provider and launcher remain synthetic."""
    import os

    from eom_identity_service.installed_owner_session_provider import (
        ProtectedInstalledIdentityProviderAdmission,
    )
    from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
    from eom_orchestrator.local_embedding_control_artifacts import (
        LocalEmbeddingControlArtifactPublisher,
    )
    from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
    from eom_workflow.reference_query_execution import parse_reference_query_execution_policy
    from eom_workflow.reference_query_owner_configuration import ReferenceQueryServiceConfiguration
    from eom_workflow_runner import reference_query_owner_runtime as runtime_module

    from tests.unit.test_reference_query_owner_runtime import configuration

    value = prepared_query
    # This older generic fixture has300s/32-task/16MiB resources. Publish a new
    # disposable control with the actual fixed CPU recipe; never relax the guard
    # or rewrite the original policy to make a bootstrap test pass.
    body = value.source.policy.model_dump(mode="json")
    body["resource_profile"] = seal(
        body["resource_profile"]
        | {"timeout_seconds": 180, "tasks_max": 64, "output_max_bytes": 64 * 1024**2},
        "resource_profile_sha256",
    )
    policy = parse_reference_query_execution_policy(seal(body, "policy_sha256"))
    published = LocalEmbeddingControlArtifactPublisher(
        value.source.publisher, source_commit="a" * 40
    ).publish_reference_query_policy(
        policy, idempotency_key="synthetic-service-boot:" + value.key, created_at=policy.created_at
    )
    body = configuration(value.source, observation).model_dump(mode="json")
    with Session(value.engine) as session, session.begin():
        role_name, role_oid = session.execute(
            text(
                "SELECT CURRENT_USER,role.oid::pg_catalog.int8 "
                "FROM pg_catalog.pg_roles role WHERE role.rolname=CURRENT_USER"
            )
        ).one()
    body["native_execution_policy"] = published.member.model_dump(mode="json")
    body["native_execution_policy_sha256"] = policy.policy_sha256
    selected = ReferenceQueryServiceConfiguration.model_validate(body)
    from eom_workflow.local_indexing_owner_configuration import LocalIndexingOwnerDatabasePin

    database_check = runtime_module.require_reference_query_database_owner

    def check_disposable_connection(session, expected):
        # The released deployment schema stays eom_app-only. This existing
        # synthetic boot fixture maps that pin to its guarded test owner; it
        # does not create/use a production role or weaken the schema.
        assert expected == selected.database_owner
        database_check(
            session, LocalIndexingOwnerDatabasePin(role_name=role_name, role_oid=role_oid)
        )

    monkeypatch.setattr(
        runtime_module, "require_reference_query_database_owner", check_disposable_connection
    )
    if fault == "space":
        body = selected.model_dump(mode="json")
        body["namespace"]["space_sha256"] = "sha256:" + "0" * 64
        selected = ReferenceQueryServiceConfiguration.model_validate(body)
    state = tmp_path / "service-state"
    state.mkdir(mode=0o700)
    (state / "workspaces").mkdir(mode=0o700)
    (state / "staging").mkdir(mode=0o700)
    monkeypatch.setattr(runtime_module, "REFERENCE_QUERY_SERVICE_STATE_ROOT", state)
    monkeypatch.setattr(
        runtime_module,
        "fixed_owner_identity",
        lambda: CpuHandoffIdentity(os.geteuid(), os.getegid()),
    )
    monkeypatch.setattr(runtime_module.os, "getgroups", lambda: [])
    monkeypatch.setattr(
        runtime_module, "build_native_embedding_controller_engine", lambda: value.engine
    )
    monkeypatch.setattr(
        runtime_module,
        "Settings",
        lambda **kwargs: replace(value.source.publisher.settings, **kwargs),
    )
    verifier = Mock(spec=runtime_module.FixedIndexingRuntimeVerification)
    launcher = Mock(spec=runtime_module.FixedNativeQueryLauncher)
    monkeypatch.setattr(
        runtime_module, "FixedIndexingRuntimeVerification", Mock(return_value=verifier)
    )
    monkeypatch.setattr(runtime_module, "FixedNativeQueryLauncher", Mock(return_value=launcher))
    dispose = Mock(wraps=value.engine.dispose)
    monkeypatch.setattr(value.engine, "dispose", dispose)

    def counts():
        with Session(value.engine) as session:
            return tuple(
                session.scalar(select(func.count()).select_from(model))
                for model in (
                    JobRecord,
                    ArtifactRevisionRecord,
                    WorkflowInstanceRecord,
                    WorkflowCommandRecord,
                )
            )

    before = counts()
    admission = ProtectedInstalledIdentityProviderAdmission(observation[0])
    if fault == "space":
        with pytest.raises(ValueError, match="OWNER_SPACE_UNAVAILABLE"):
            runtime_module.build_reference_query_owner_runtime(selected, admission)
        launcher.assert_current_runtime.assert_not_called()
        dispose.assert_called_once()
    else:
        runtime = runtime_module.build_reference_query_owner_runtime(selected, admission)
        launcher.assert_current_runtime.assert_called_once()
        launcher.run.assert_not_called()
        first = runtime.application(value.source.owner.identity.capture)
        second = runtime.application(value.source.owner.identity.capture)
        assert first.owner is not second.owner and first.driver is runtime.driver is second.driver
        assert not runtime.driver.observe().active
        runtime.close()
        dispose.assert_called_once()
    assert counts() == before and value.source.calls == []


@pytest.mark.parametrize("fault", ("none", "role", "oid"))
def test_actual_read_only_connection_check_rejects_wrong_role_or_oid(guarded_engine, fault):
    from eom_workflow.local_indexing_owner_configuration import LocalIndexingOwnerDatabasePin
    from eom_workflow_runner.reference_query_owner_runtime import (
        require_reference_query_database_owner,
    )

    with Session(guarded_engine) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        role_name, role_oid = session.execute(
            text(
                "SELECT CURRENT_USER,oid::pg_catalog.int8 FROM pg_roles WHERE rolname=CURRENT_USER"
            )
        ).one()
        expected = LocalIndexingOwnerDatabasePin(
            role_name="synthetic_wrong_owner" if fault == "role" else role_name,
            role_oid=role_oid + 1 if fault == "oid" else role_oid,
        )
        if fault == "none":
            require_reference_query_database_owner(session, expected)
        else:
            with pytest.raises(ValueError, match="DATABASE_ROLE_MISMATCH"):
                require_reference_query_database_owner(session, expected)
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert not session.new and not session.dirty and not session.deleted


@pytest.fixture
def prepared_application(prepared_query, monkeypatch):
    value = prepared_query
    wire = wire_request(value.source, key=value.key)
    key, context_id = reference_query_prepare_identity(
        value.caller.operator_id, wire.idempotency_key
    )
    context = value.context.model_dump(mode="json")
    context["request_id"] = context_id
    context["views"].append(
        {"view": "METADATA_ONLY", "recipe": context["views"][0]["recipe"], "index": None}
    )
    context = parse_similarity_context_request(seal(context, "request_sha256"))
    value.context = context
    value.source.request = parse_supported_reference_query_workflow_request(
        seal(
            value.source.request.model_dump(mode="json")
            | {"context_request": context.model_dump(mode="json")},
            "request_sha256",
        )
    )
    value.source.prepared = replace(value.source.prepared, request_sha256=context.request_sha256)

    def anchor(session, caller, current):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert caller == value.caller and current == value.context
        validate_similarity_preparation(current, value.source.prepared)
        return value.source.prepared

    initial = Mock(side_effect=lambda *_: value.context)
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_anchor_in_session", anchor
    )
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_context_in_session", initial
    )
    driver = ReferenceQueryPrepareDriver()
    runner = query_runner(value.source.owner, value.executor)
    app = NativeReferenceQueryPreparation(
        owner=value.source.owner,
        executor=value.executor,
        runner=runner,
        driver=driver,
        spaces=value.source.policy.spaces,
    )
    offers = []

    def offer(workflow_id, actual_runner):
        # A distinct real PostgreSQL connection can see both rows: physical drive
        # is never offered before admission/START commit.
        assert actual_runner is runner
        with Session(value.engine) as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.idempotency_key == key
            assert (
                session.scalar(
                    select(WorkflowCommandRecord.command_id).where(
                        WorkflowCommandRecord.idempotency_key == "start:" + workflow_id
                    )
                )
                is not None
            )
        offers.append(workflow_id)
        return "BUSY"

    monkeypatch.setattr(driver, "offer", offer)
    return SimpleNamespace(value=value, app=app, wire=wire, key=key, offers=offers, initial=initial)


def workflow_counts(case):
    with Session(case.value.engine) as session:
        workflow = session.scalar(
            select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == case.key)
        )
        if workflow is None:
            return 0, 0
        return 1, session.scalar(
            select(func.count())
            .select_from(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
        )


@pytest.mark.parametrize(
    "prepared_query", ("PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"), indirect=True
)
def test_real_application_commits_before_offer_and_replay_preserves_original(prepared_application):
    case = prepared_application
    first = case.app.prepare(case.wire)
    assert first.status == "PENDING" and first.selection is None
    with Session(case.value.engine) as session:
        original = session.get(WorkflowInstanceRecord, first.workflow_id).initial_request
    case.initial.side_effect = AssertionError("recapturing initial source on replay")
    second = case.app.prepare(
        wire_request(case.value.source, key=case.wire.idempotency_key, operation="b")
    )
    assert second.status == "PENDING" and second.workflow_id == first.workflow_id
    assert second.request_sha256 != first.request_sha256
    with Session(case.value.engine) as session:
        assert session.get(WorkflowInstanceRecord, first.workflow_id).initial_request == original
    assert workflow_counts(case) == (1, 1)
    assert case.offers == [first.workflow_id, first.workflow_id]
    case.value.executor.execute.assert_not_called()
    case.value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize(
    "prepared_query", ("PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"), indirect=True
)
def test_same_key_concurrent_application_uses_one_workflow_start(prepared_application):
    case = prepared_application
    barrier = Barrier(2)

    def initial(*_args):
        barrier.wait(timeout=10)
        return case.value.context

    case.initial.side_effect = initial
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = tuple(pool.map(lambda _: case.app.prepare(case.wire), range(2)))
    assert all(reply.status == "PENDING" for reply in replies)
    assert replies[0].workflow_id == replies[1].workflow_id
    assert workflow_counts(case) == (1, 1)
    case.value.executor.execute.assert_not_called()


@pytest.mark.parametrize("field", ("source", "policy", "graph"))
@pytest.mark.parametrize(
    "prepared_query", ("PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"), indirect=True
)
def test_changed_same_key_intent_never_creates_replacement_work(prepared_application, field):
    case = prepared_application
    first = case.app.prepare(case.wire)
    body = case.wire.model_dump(mode="json")
    if field == "source":
        body["source_item_revision_id"] = "itemrev_" + "f" * 32
    elif field == "policy":
        body["policy_sha256"] = "sha256:" + "f" * 64
    else:
        body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    from eom_catalog_contracts.reference_query_prepare import (
        parse_supported_reference_query_prepare_request,
    )

    changed = parse_supported_reference_query_prepare_request(seal(body, "request_sha256"))
    reply = case.app.prepare(changed)
    assert reply.status == "FAILED" and reply.selection is None
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]


@pytest.mark.parametrize(
    "prepared_query", ("PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"), indirect=True
)
def test_same_key_purpose_change_cannot_relabel_or_replace_existing_work(prepared_application):
    from eom_catalog_contracts.reference_query_prepare import (
        parse_supported_reference_query_prepare_request,
    )

    case = prepared_application
    first = case.app.prepare(case.wire)
    with Session(case.value.engine) as session:
        original = session.get(WorkflowInstanceRecord, first.workflow_id).initial_request
    changed = case.wire.model_dump(mode="json") | {
        "schema_version": "system-rag-reference-query-prepare-request/1.1",
        "consumer_purpose": (
            "ITEM_REVIEW"
            if case.value.context.consumer_purpose == "ITEM_AUTHORING"
            else "ITEM_AUTHORING"
        ),
    }
    case.initial.side_effect = AssertionError("same-key replay must not capture another source")
    reply = case.app.prepare(
        parse_supported_reference_query_prepare_request(seal(changed, "request_sha256"))
    )
    assert reply.status == "FAILED" and reply.selection is None
    assert reply.error_code == "SOURCE_POINTER_INVALID"
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]
    with Session(case.value.engine) as session:
        assert session.get(WorkflowInstanceRecord, first.workflow_id).initial_request == original


@pytest.mark.parametrize("missing", ("report", "index"))
def test_known_absence_persists_no_queue_work(prepared_application, missing):
    case = prepared_application
    body = case.value.context.model_dump(mode="json")
    if missing == "report":
        body["anchor"]["profile"] = body["anchor"]["solution_evidence"] = None
    else:
        for row in body["views"]:
            row["index"] = None
    case.value.context = parse_similarity_context_request(seal(body, "request_sha256"))
    reply = case.app.prepare(case.wire)
    assert reply.status == "UNAVAILABLE"
    assert workflow_counts(case) == (0, 0) and case.offers == []


def test_late_current_denial_rolls_back_admission_and_start(prepared_application, monkeypatch):
    case = prepared_application
    original = case.value.source.owner.resolve_submission
    calls = 0

    def deny_late(session, request):
        nonlocal calls
        calls += 1
        result = original(session, request)
        if calls == 4:
            raise OperatorAuthorizationFenceError("synthetic late authority revocation")
        return result

    monkeypatch.setattr(case.value.source.owner, "resolve_submission", deny_late)
    reply = case.app.prepare(case.wire)
    assert reply.status == "FAILED" and reply.error_code == "AUTHORITY_UNAVAILABLE"
    assert calls == 4 and workflow_counts(case) == (0, 0) and case.offers == []


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED", "COMPLETED", "AWAITING_HUMAN_APPROVAL"))
def test_state_alone_never_grants_ready_or_restart(prepared_application, state):
    case = prepared_application
    first = case.app.prepare(case.wire)
    # Deliberately inject impossible terminal metadata in the disposable fixture.
    # No canonical Job/result/receipt is fabricated to make this a success.
    with Session(case.value.engine) as session, session.begin():
        session.get(WorkflowInstanceRecord, first.workflow_id).state = state
    reply = case.app.prepare(case.wire)
    assert reply.status == "FAILED" and reply.selection is None
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]
