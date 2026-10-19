"""Synthetic mixed submission/queue roots and real temp control owner, not activation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.local_embedding_control_artifacts import (
    SOURCE_PLAN_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.local_embedding_request_v2 import parse_local_embedding_workflow_request_v2
from eom_workflow.local_embedding_source_plan_v2 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_submission import (
    LocalEmbeddingCoverageOnly,
    LocalEmbeddingWorkflowSubmitted,
    start_local_embedding_in_session,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    NativeCommandActorSelection,
    claim_command_candidate,
    load_persisted_local_embedding_workflow_request,
    local_embedding_business_fingerprint,
    peek_command_candidate,
    validate_local_embedding_workflow_submission,
    workflow_request_storage_document,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import member, native_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_embedding_command_claim import prepare_claim
from tests.unit.test_local_embedding_submission import submission_fixture
from tests.unit.test_mixed_local_embedding_owner_admission import mixed_scope


def fixture(*, empty=False):
    c = submission_fixture()
    scope, compiled, _grant = mixed_scope()
    if empty:
        plan = parse_local_embedding_source_plan_v2(
            seal(
                scope.plan.model_dump(mode="json")
                | {
                    "demands": [],
                    "missing_solution_report_revision_ids": [
                        s.item_revision_id for s in scope.plan.sources
                    ],
                    "encoding_set_sha256": embedding_input_set_sha256(()),
                },
                "plan_sha256",
            )
        )
        request = parse_local_embedding_workflow_request_v2(
            seal(
                scope.request.model_dump(mode="json")
                | {
                    "source_plan": member(
                        "source-plan.json",
                        LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
                        plan.model_dump(mode="json"),
                        "2",
                    ).model_dump(mode="json"),
                    "source_plan_sha256": plan.plan_sha256,
                },
                "request_sha256",
            )
        )
        scope = ResolvedLocalEmbeddingAdmission(request, plan, scope.policy)
    c.scope, c.compiled = scope, compiled
    c.definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "2" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )
    return c


def submit(c, **changes):
    values = dict(
        definition=c.definition,
        request=c.scope.request,
        idempotency_key="synthetic-mixed-submit",
        actor_type="local_indexing_service",
        actor_id=c.scope.request.actor_context.service_id,
        owner=c.owner,
        executor=c.executor,
    )
    values.update(changes)
    return start_local_embedding_in_session(c.session, **values)


def test_exact_request2_storage_and_same_key_submission_use_existing_rows_events():
    c = fixture()
    document = workflow_request_storage_document(c.scope.request)
    assert document == c.scope.request.model_dump(mode="json")
    assert load_persisted_local_embedding_workflow_request(document) == c.scope.request
    first = submit(c)
    assert isinstance(first, LocalEmbeddingWorkflowSubmitted)
    saved_rows = tuple(c.rows)
    replay = submit(c)
    assert replay.workflow is first.workflow and replay.command is first.command
    assert first.workflow_created and first.command_created
    assert not replay.workflow_created and not replay.command_created
    assert tuple(c.rows) == saved_rows
    assert first.workflow.stage == "LOCAL_EMBEDDING"
    assert first.workflow.definition_version == "2.0.0"
    assert first.workflow.role_schema_version == "local-embedding/1.0"
    assert first.workflow.initial_request == first.workflow.request_payload == document
    assert first.command.actor_type == first.workflow.created_actor_type == "local_indexing_service"
    c.executor.evaluate.assert_not_called()
    c.executor.execute.assert_not_called()


def test_actor_bound_business_hash_keeps_new_definition_identity_distinct():
    c = fixture()
    actor_id = c.scope.request.actor_context.service_id
    expected = content_sha256(
        {
            "definition_key": c.definition.definition_key,
            "definition_version": "2.0.0",
            "definition_hash": c.compiled.sha256,
            "request": c.scope.request.model_dump(mode="json"),
            "actor": {"actor_type": "local_indexing_service", "actor_id": actor_id},
        }
    )
    assert (
        local_embedding_business_fingerprint(
            c.definition, c.scope.request, actor_type="local_indexing_service", actor_id=actor_id
        )
        == expected
    )
    assert (
        local_embedding_business_fingerprint(
            c.definition,
            c.scope.request,
            actor_type="local_indexing_service",
            actor_id="localindexservice_" + "f" * 32,
        )
        != expected
    )


@pytest.mark.parametrize("fault", ("actor", "definition", "extra", "denial", "late_denial"))
def test_invalid_mixed_start_never_leaves_partial_workflow_or_command(fault):
    c = fixture()
    changes = {}
    if fault == "actor":
        changes.update(actor_type="human", actor_id="operator_" + "1" * 32)
    elif fault == "definition":
        c.definition = submission_fixture().definition
    elif fault == "extra":
        changes["request"] = c.scope.request.model_copy(update={"undeclared": "forbidden"})
    else:
        c.deny_at = 1 if fault == "denial" else 3
    with pytest.raises(ValueError):
        submit(c, **changes)
    assert c.rows == []


def test_mixed_coverage_only_returns_validated_plan_without_queue_or_compute():
    c = fixture(empty=True)
    result = submit(c)
    assert isinstance(result, LocalEmbeddingCoverageOnly) and result.plan == c.scope.plan
    assert c.owner_depths == [0, 0] and c.rows == []
    c.session.begin_nested.assert_not_called()
    c.executor.evaluate.assert_not_called()
    c.executor.execute.assert_not_called()
    with pytest.raises(ValueError):
        LocalEmbeddingCoverageOnly(c.scope.plan.model_copy(update={"undeclared": "forbidden"}))


def test_exact_mixed_candidate_and_shared_claim_fences_never_enter_role_execution():
    c = fixture()
    result = submit(c)
    workflow, command = result.workflow, result.command
    now = datetime.now(UTC)
    command.created_at = now - timedelta(seconds=2)
    command.available_at = now - timedelta(seconds=1)
    command.lease_generation = 0
    command.lease_expires_at = None
    workflow.created_at = now - timedelta(seconds=3)
    c.session.execute.return_value.one_or_none.return_value = command, workflow
    selection = NativeCommandActorSelection(
        "local_indexing_service",
        c.scope.request.actor_context.service_id,
        c.scope.request.namespace,
    )
    candidate = peek_command_candidate(
        c.session, family=CommandExecutionFamily.LOCAL_EMBEDDING, actor_selection=selection
    )
    assert candidate is not None and candidate.native_request == c.scope.request
    assert "local-embedding-workflow-request/2.0" in {
        value
        for param in c.session.execute.call_args.args[0].compile().params.values()
        for value in (param if isinstance(param, tuple | list) else (param,))
        if isinstance(value, str)
    }
    order = prepare_claim(c, workflow, command)
    assert (
        claim_command_candidate(
            c.session,
            candidate,
            runner_id="synthetic-mixed-runner",
            lease_seconds=60,
            local_embedding_owner=c.owner,
            local_embedding_executor=c.executor,
        )
        is command
    )
    assert order[:3] == ["workflow", "command", "owner-before-lease"]
    assert order[-1] == "owner-late" and command.lease_generation == 1
    assert command.state == "LEASED" and command.attempts == 1
    c.executor.execute.assert_not_called()


@pytest.mark.parametrize("fault", ("definition", "payload", "actor", "hash"))
def test_exact_mixed_submission_replay_revalidates_current_metadata(fault):
    c = fixture()
    result = submit(c)
    if fault == "definition":
        c.definition.definition_version = "1.0.0"
    elif fault == "payload":
        result.workflow.request_payload = {**result.workflow.request_payload, "undeclared": "bad"}
    elif fault == "actor":
        result.workflow.created_actor_type = "human"
    else:
        result.workflow.request_hash = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="SUBMISSION_REPLAY_INVALID"):
        validate_local_embedding_workflow_submission(
            c.session,
            result.workflow,
            definition=c.definition,
            request=c.scope.request,
            actor_type="local_indexing_service",
            actor_id=c.scope.request.actor_context.service_id,
        )


def test_mixed_selector_does_not_accept_copied_extra_namespace():
    c = fixture()
    with pytest.raises(ValueError):
        NativeCommandActorSelection(
            "local_indexing_service",
            c.scope.request.actor_context.service_id,
            c.scope.request.namespace.model_copy(update={"undeclared": "bad"}),
        )


@pytest.mark.parametrize("observed", (False, True))
def test_explicit_mixed_plan_control_publication_and_same_pinned_reader(tmp_path, observed):
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    scope, _compiled, _grant = mixed_scope()
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)

    def publish(plan):
        if observed:
            return controls.publish_observed_source_plan_v2(
                plan, idempotency_key="synthetic-mixed-plan:fixed"
            )
        return controls.publish_source_plan_v2(
            plan, idempotency_key="synthetic-mixed-plan:fixed", created_at=scope.policy.created_at
        )

    first, replay = publish(scope.plan), publish(scope.plan)
    assert first == replay and first.semantic_sha256 == scope.plan.plan_sha256
    raw = canonical_json_bytes(scope.plan.model_dump(mode="json"))
    assert first.member.schema_ref == LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF
    assert first.member.sha256 == sha256_bytes(raw)
    with publisher.sessions() as session, session.begin():
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((first.member.artifact_id, first.member.artifact_revision_id),))
        resolved = reader.read_pinned(
            **first.member.model_dump(mode="python"),
            expected_artifact_types=(SOURCE_PLAN_ARTIFACT_TYPE,),
            expected_primary_file="source-plan.json",
            max_bytes=64 * 1024**2,
        )
        assert resolved.payload == raw
    with pytest.raises(ValueError):
        controls.publish_source_plan(
            scope.plan, idempotency_key="not-old-plan", created_at=scope.policy.created_at
        )
    with pytest.raises(ValueError):
        publish(native_fixture().plan)
    with pytest.raises(ValueError):
        publish(scope.plan.model_copy(update={"undeclared": "bad"}))
