"""Synthetic source gates only: no actual DB, source, session or runtime admission."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_identifiers import content_sha256
from eom_workflow.compiler import CompiledWorkflowDefinition
from eom_workflow.local_embedding_request import (
    LocalEmbeddingWorkflowRequestV11,
    require_local_embedding_operator_seed,
)
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingAdmission,
)
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.local_embedding_submission import (
    LocalEmbeddingCoverageOnly,
    LocalEmbeddingWorkflowSubmitted,
    start_local_embedding_in_session,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    create_workflow_instance,
    import_workflow_definition,
    load_persisted_local_embedding_workflow_request,
    load_persisted_workflow_request,
    local_embedding_business_fingerprint,
    workflow_definition_admission_statuses,
    workflow_request_storage_document,
)
from eom_workflow_runner.state_machine import WorkflowStage
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_local_embedding_runner_admission import scope_fixture

OPERATOR = "operator_" + "1" * 32


@dataclass
class SyntheticSubmission:
    """Bounded metadata-only SQL spy; its rows/fences are not integration evidence."""

    scope: ResolvedLocalEmbeddingAdmission
    compiled: CompiledWorkflowDefinition
    definition: WorkflowDefinitionRecord
    session: Mock
    owner: Mock
    executor: Mock
    rows: list[Any]
    depth: int = 0
    rollback_count: int = 0
    owner_depths: list[int] | None = None
    deny_at: int | None = None

    def submit(self, *, key: str = "synthetic-native:start") -> Any:
        return start_local_embedding_in_session(
            cast(Session, self.session),
            definition=self.definition,
            request=self.scope.request,
            idempotency_key=key,
            actor_type="human",
            actor_id=require_local_embedding_operator_seed(self.scope.request).operator_id,
            owner=cast(LocalEmbeddingOwnerAdmission, self.owner),
            executor=cast(LocalEmbeddingNativeExecutor, self.executor),
        )

    def scalar(self, query: Any) -> Any:
        model = query.column_descriptions[0]["entity"]
        parameters = query.compile().params
        if model is WorkflowDefinitionRecord:
            return self.definition
        candidates = [row for row in self.rows if isinstance(row, model)]
        for field in ("workflow_id", "idempotency_key", "request_hash"):
            expected = parameters.get(f"{field}_1")
            if expected is not None:
                candidates = [row for row in candidates if getattr(row, field) == expected]
        state = parameters.get("state_1")
        if state is not None:
            states = state if isinstance(state, tuple | list) else (state,)
            candidates = [row for row in candidates if row.state in states]
        return candidates[0] if candidates else None

    @contextmanager
    def savepoint(self) -> Any:
        original = len(self.rows)
        self.depth += 1
        try:
            yield
        except Exception:
            del self.rows[original:]
            self.rollback_count += 1
            raise
        finally:
            self.depth -= 1

    def resolve(self, session: Session, request: LocalEmbeddingWorkflowRequestV11) -> Any:
        assert session is self.session
        assert self.owner_depths is not None
        self.owner_depths.append(self.depth)
        if self.deny_at == len(self.owner_depths):
            raise ValueError("SYNTHETIC_CURRENT_OWNER_REVOKED")
        assert request == self.scope.request
        return self.scope


def submission_fixture(*, empty: bool = False) -> SyntheticSubmission:
    scope, compiled = scope_fixture()
    if empty:
        plan = type(scope.plan).model_validate(
            seal(
                scope.plan.model_dump(mode="json")
                | {
                    "demands": [],
                    "missing_solution_report_revision_ids": [
                        source.item_revision_id for source in scope.plan.sources
                    ],
                    "encoding_set_sha256": embedding_input_set_sha256(()),
                },
                "plan_sha256",
            )
        )
        request = LocalEmbeddingWorkflowRequestV11.model_validate(
            seal(
                scope.request.model_dump(mode="json")
                | {
                    "source_plan": member(
                        "source-plan.json",
                        scope.request.source_plan.schema_ref,
                        plan.model_dump(mode="json"),
                        "2",
                    ).model_dump(mode="json"),
                    "source_plan_sha256": plan.plan_sha256,
                },
                "request_sha256",
            )
        )
        scope = ResolvedLocalEmbeddingAdmission(request, plan, scope.policy)
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "1" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )
    session = Mock(spec=Session)
    session.is_active = True
    session.get_transaction.return_value = Mock(is_active=True)
    owner = Mock(spec=LocalEmbeddingOwnerAdmission)
    executor = Mock(spec=LocalEmbeddingNativeExecutor)
    fixture = SyntheticSubmission(scope, compiled, definition, session, owner, executor, [])
    fixture.owner_depths = []
    session.in_nested_transaction.side_effect = lambda: fixture.depth > 0
    session.scalar.side_effect = fixture.scalar
    session.begin_nested.side_effect = fixture.savepoint
    session.add.side_effect = fixture.rows.append
    session.get.side_effect = lambda model, identity: next(
        (row for row in fixture.rows if isinstance(row, model) and row.workflow_id == identity),
        None,
    )
    owner.resolve_submission.side_effect = fixture.resolve
    return fixture


def test_native_storage_is_exact_separate_from_released_role_request() -> None:
    fixture = submission_fixture()
    document = workflow_request_storage_document(fixture.scope.request)
    assert document == fixture.scope.request.model_dump(mode="json")
    assert load_persisted_local_embedding_workflow_request(document) == fixture.scope.request
    assert (
        workflow_request_storage_document(load_persisted_local_embedding_workflow_request(document))
        == document
    )
    with pytest.raises(ValueError):
        load_persisted_workflow_request(document)
    with pytest.raises(ValueError):
        load_persisted_local_embedding_workflow_request(
            document | {"schema_version": "local-embedding-workflow-request/1.0"}
        )
    missing = dict(document)
    del missing["source_plan"]
    with pytest.raises(ValueError):
        load_persisted_local_embedding_workflow_request(missing)
    bad = fixture.scope.request.model_copy(
        update={
            "resource_profile": fixture.scope.request.resource_profile.model_copy(
                update={"threads": True}
            )
        }
    )
    with pytest.raises(ValueError):
        workflow_request_storage_document(bad)
    with pytest.raises(ValueError):
        local_embedding_business_fingerprint(
            fixture.definition, bad, actor_type="human", actor_id=OPERATOR
        )


def test_native_fingerprint_exact_fields_and_cross_operator_separation() -> None:
    fixture = submission_fixture()
    request = fixture.scope.request
    expected = content_sha256(
        {
            "definition_key": fixture.definition.definition_key,
            "definition_version": fixture.definition.definition_version,
            "definition_hash": fixture.definition.definition_hash,
            "request": request.model_dump(mode="json"),
            "actor": {"actor_type": "human", "actor_id": OPERATOR},
        }
    )
    assert (
        local_embedding_business_fingerprint(
            fixture.definition, request, actor_type="human", actor_id=OPERATOR
        )
        == expected
    )
    assert (
        local_embedding_business_fingerprint(
            fixture.definition,
            request,
            actor_type="human",
            actor_id="operator_" + "2" * 32,
        )
        != expected
    )


@pytest.mark.parametrize("missing", ["owner", "executor", "both"])
def test_required_ports_precede_any_sql_or_replay(missing: str) -> None:
    fixture = submission_fixture()
    with pytest.raises(WorkflowError) as error:
        create_workflow_instance(
            cast(Session, fixture.session),
            definition=fixture.definition,
            request=fixture.scope.request,
            idempotency_key="synthetic-native:start",
            actor_type="human",
            actor_id=OPERATOR,
            local_embedding_owner=(
                None
                if missing in {"owner", "both"}
                else cast(LocalEmbeddingOwnerAdmission, fixture.owner)
            ),
            local_embedding_executor=(
                None
                if missing in {"executor", "both"}
                else cast(LocalEmbeddingNativeExecutor, fixture.executor)
            ),
        )
    assert error.value.code == WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE
    fixture.session.scalar.assert_not_called()
    fixture.session.add.assert_not_called()
    fixture.session.begin_nested.assert_not_called()


def test_actual_owner_denial_precedes_definition_lookup_and_writes() -> None:
    fixture = submission_fixture()
    fixture.deny_at = 1
    with pytest.raises(ValueError, match="SYNTHETIC_CURRENT_OWNER_REVOKED"):
        fixture.submit()
    fixture.session.scalar.assert_not_called()
    fixture.session.add.assert_not_called()
    fixture.session.begin_nested.assert_not_called()


@pytest.mark.parametrize("invalid", ["inactive", "hash", "snapshot", "version", "audit"])
def test_zero_demand_does_not_bypass_exact_definition_or_audit(invalid: str) -> None:
    fixture = submission_fixture(empty=True)
    if invalid == "inactive":
        fixture.definition.active = False
    elif invalid == "hash":
        fixture.definition.definition_hash = sha("0")
    elif invalid == "snapshot":
        fixture.definition.canonical_definition = fixture.compiled.as_dict() | {
            "start_step": "complete"
        }
    elif invalid == "version":
        fixture.definition.definition_version = "1.0.1"
    else:
        fixture.scope = ResolvedLocalEmbeddingAdmission(
            LocalEmbeddingWorkflowRequestV11.model_validate(
                seal(
                    fixture.scope.request.model_dump(mode="json")
                    | {
                        "actor_context": fixture.scope.request.actor_context.model_dump(mode="json")
                        | {"operator_id": "operator_" + "2" * 32}
                    },
                    "request_sha256",
                )
            ),
            fixture.scope.plan,
            fixture.scope.policy,
        )
        with pytest.raises(ValueError, match="LOCAL_EMBEDDING_OPERATOR_UNAVAILABLE"):
            start_local_embedding_in_session(
                cast(Session, fixture.session),
                definition=fixture.definition,
                request=fixture.scope.request,
                idempotency_key="synthetic-zero:start",
                actor_type="human",
                actor_id=OPERATOR,
                owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
                executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
            )
        assert fixture.rows == []
        return
    with pytest.raises(ValueError):
        fixture.submit()
    assert fixture.rows == []
    fixture.session.begin_nested.assert_not_called()


def test_valid_zero_demand_checks_owner_twice_and_returns_no_rows() -> None:
    fixture = submission_fixture(empty=True)
    result = fixture.submit()
    assert isinstance(result, LocalEmbeddingCoverageOnly)
    assert result.plan == fixture.scope.plan
    assert fixture.owner_depths == [0, 0]
    fixture.session.add.assert_not_called()
    fixture.session.flush.assert_not_called()
    fixture.session.begin_nested.assert_not_called()
    fixture.executor.evaluate.assert_not_called()
    fixture.executor.execute.assert_not_called()
    with pytest.raises(ValueError):
        LocalEmbeddingCoverageOnly(submission_fixture().scope.plan)


def test_repository_compute_guard_still_rejects_zero_after_full_owner_closure() -> None:
    fixture = submission_fixture(empty=True)
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_COVERAGE_ONLY"):
        create_workflow_instance(
            cast(Session, fixture.session),
            definition=fixture.definition,
            request=fixture.scope.request,
            idempotency_key="synthetic-zero:start",
            actor_type="human",
            actor_id=OPERATOR,
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    assert fixture.owner_depths == [0]
    assert fixture.rows == []
    fixture.session.begin_nested.assert_not_called()


def test_copied_invalid_request_is_rejected_before_owner_or_sql() -> None:
    fixture = submission_fixture()
    request = fixture.scope.request.model_copy(
        update={
            "resource_profile": fixture.scope.request.resource_profile.model_copy(
                update={"threads": True}
            )
        }
    )
    with pytest.raises(ValueError):
        start_local_embedding_in_session(
            cast(Session, fixture.session),
            definition=fixture.definition,
            request=request,
            idempotency_key="synthetic-invalid:start",
            actor_type="human",
            actor_id=OPERATOR,
            owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    fixture.owner.resolve_submission.assert_not_called()
    fixture.session.scalar.assert_not_called()
    assert fixture.rows == []


def test_owner_cannot_substitute_a_different_exact_request_or_invalid_controls() -> None:
    fixture = submission_fixture(empty=True)
    other = submission_fixture()
    fixture.owner.resolve_submission.side_effect = None
    fixture.owner.resolve_submission.return_value = other.scope
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_SUBMISSION_CONTEXT_INVALID"):
        fixture.submit()
    fixture.session.scalar.assert_not_called()
    bad = object.__new__(ResolvedLocalEmbeddingAdmission)
    for field, value in (
        ("request", fixture.scope.request),
        ("plan", fixture.scope.plan),
        ("policy", fixture.scope.policy.model_copy(update={"policy_sha256": sha("0")})),
    ):
        object.__setattr__(bad, field, value)
    fixture.owner.resolve_submission.return_value = bad
    with pytest.raises(ValueError):
        fixture.submit()
    assert fixture.rows == []


def test_native_cannot_receive_legacy_runtime_context_before_any_lookup() -> None:
    fixture = submission_fixture()
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            cast(Session, fixture.session),
            definition=fixture.definition,
            request=fixture.scope.request,
            idempotency_key="synthetic-foreign-context:start",
            actor_type="human",
            actor_id=OPERATOR,
            runtime_context={"arbitrary": "legacy-context"},
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    fixture.session.scalar.assert_not_called()
    fixture.session.begin_nested.assert_not_called()


def test_nonzero_submission_creates_exact_workflow_and_start_atomically() -> None:
    fixture = submission_fixture()
    result = fixture.submit()
    assert isinstance(result, LocalEmbeddingWorkflowSubmitted)
    assert result.workflow_created and result.command_created
    assert result.workflow.stage == WorkflowStage.LOCAL_EMBEDDING.value
    assert result.workflow.role_schema_version == "local-embedding/1.0"
    assert result.workflow.request_payload == fixture.scope.request.model_dump(mode="json")
    assert result.command.workflow_id == result.workflow.workflow_id
    assert result.command.payload == {}
    assert result.command.command_type == "START_WORKFLOW"
    assert len([row for row in fixture.rows if isinstance(row, WorkflowInstanceRecord)]) == 1
    assert len([row for row in fixture.rows if isinstance(row, WorkflowCommandRecord)]) == 1
    assert len([row for row in fixture.rows if isinstance(row, WorkflowEventRecord)]) == 1
    assert fixture.owner_depths == [0, 1, 2, 1]
    fixture.executor.evaluate.assert_not_called()
    fixture.executor.execute.assert_not_called()
    fixture.session.commit.assert_not_called()
    fixture.session.rollback.assert_not_called()


@pytest.mark.parametrize("completed", [False, True])
def test_same_key_and_active_completed_reuse_original_start_without_new_command(
    completed: bool,
) -> None:
    fixture = submission_fixture()
    first = fixture.submit()
    if completed:
        first.workflow.state = "COMPLETED"
        first.workflow.stage = "COMPLETED"
        first.command.state = "SUCCEEDED"
    before = tuple(fixture.rows)
    replay = fixture.submit()
    equivalent = fixture.submit(key="synthetic-native:equivalent")
    for result in (replay, equivalent):
        assert result.workflow is first.workflow and result.command is first.command
        assert not result.workflow_created and not result.command_created
    assert tuple(fixture.rows) == before
    assert len(fixture.owner_depths or []) == 12


def test_cross_actor_same_key_conflict_and_distinct_equivalent_workflow() -> None:
    fixture = submission_fixture()
    first = fixture.submit()
    request = LocalEmbeddingWorkflowRequestV11.model_validate(
        seal(
            fixture.scope.request.model_dump(mode="json")
            | {
                "actor_context": fixture.scope.request.actor_context.model_dump(mode="json")
                | {"operator_id": "operator_" + "2" * 32}
            },
            "request_sha256",
        )
    )
    fixture.scope = ResolvedLocalEmbeddingAdmission(
        request, fixture.scope.plan, fixture.scope.policy
    )
    with pytest.raises(WorkflowError) as error:
        fixture.submit()
    assert error.value.code == WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE
    other = fixture.submit(key="synthetic-native:other-operator")
    assert other.workflow.workflow_id != first.workflow.workflow_id
    assert other.workflow.request_hash != first.workflow.request_hash
    assert other.command.command_id != first.command.command_id


@pytest.mark.parametrize("bad", ["missing_start", "command_hash", "workflow_payload"])
def test_replay_rejects_corrupted_history_without_repair(bad: str) -> None:
    fixture = submission_fixture()
    first = fixture.submit()
    if bad == "missing_start":
        fixture.rows.remove(first.command)
    elif bad == "command_hash":
        first.command.request_hash = sha("0")
    else:
        first.workflow.request_payload = {}
    before = tuple(fixture.rows)
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_SUBMISSION_REPLAY_INVALID"):
        fixture.submit()
    assert tuple(fixture.rows) == before


@pytest.mark.parametrize("deny_at", [3, 4])
def test_late_owner_failure_rolls_back_all_new_metadata(deny_at: int) -> None:
    fixture = submission_fixture()
    fixture.deny_at = deny_at
    with pytest.raises(ValueError, match="SYNTHETIC_CURRENT_OWNER_REVOKED"):
        fixture.submit()
    assert fixture.rows == []
    assert fixture.rollback_count > 0
    fixture.session.commit.assert_not_called()


def test_owner_denial_on_replay_preserves_original_history() -> None:
    fixture = submission_fixture()
    fixture.submit()
    before = tuple(fixture.rows)
    fixture.deny_at = len(fixture.owner_depths or []) + 4
    with pytest.raises(ValueError, match="SYNTHETIC_CURRENT_OWNER_REVOKED"):
        fixture.submit()
    assert tuple(fixture.rows) == before


def test_native_direct_repository_replay_uses_same_exact_row_closure() -> None:
    fixture = submission_fixture()
    first = fixture.submit()
    first.workflow.created_actor_id = "operator_" + "2" * 32
    before = tuple(fixture.rows)
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_SUBMISSION_REPLAY_INVALID"):
        create_workflow_instance(
            cast(Session, fixture.session),
            definition=fixture.definition,
            request=fixture.scope.request,
            idempotency_key="synthetic-native:start",
            actor_type="human",
            actor_id=OPERATOR,
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    assert tuple(fixture.rows) == before


def test_native_definition_and_replay_reads_request_identity_map_refresh() -> None:
    fixture = submission_fixture()
    fixture.submit()
    fixture.submit()
    root = fixture.session.get_transaction.return_value
    assert root.is_active is True
    assert all(
        call.args[0] is fixture.session for call in fixture.owner.resolve_submission.call_args_list
    )
    definition_queries = []
    workflow_pk_queries = []
    for call in fixture.session.scalar.call_args_list:
        query = call.args[0]
        model = query.column_descriptions[0]["entity"]
        if model is WorkflowDefinitionRecord:
            definition_queries.append(query)
        elif model is WorkflowInstanceRecord and "workflow_id_1" in query.compile().params:
            workflow_pk_queries.append(query)
    assert definition_queries and workflow_pk_queries
    for query in definition_queries:
        assert query.get_execution_options()["populate_existing"] is True
        assert query._for_update_arg is None
    for query in workflow_pk_queries:
        assert query.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("invalid", ["root_missing", "nested", "purpose", "legacy_request"])
def test_no_root_or_foreign_purpose_refused_without_writes(invalid: str) -> None:
    fixture = submission_fixture()
    if invalid == "root_missing":
        fixture.session.get_transaction.return_value = None
    elif invalid == "nested":
        fixture.depth = 1
    elif invalid == "purpose":
        fixture.definition.definition_key = "generic-item-development"
    if invalid == "legacy_request":
        with pytest.raises(WorkflowError):
            create_workflow_instance(
                cast(Session, fixture.session),
                definition=fixture.definition,
                request=WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip"),
                idempotency_key="synthetic-foreign:start",
                actor_type="human",
                actor_id=OPERATOR,
                local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
                local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
            )
    else:
        with pytest.raises((ValueError, WorkflowError)):
            fixture.submit()
    assert fixture.rows == []


def test_native_import_and_stored_admission_use_execution_not_role_protocol() -> None:
    fixture = submission_fixture()
    imported, created = import_workflow_definition(cast(Session, fixture.session), fixture.compiled)
    assert imported is fixture.definition and not created
    fixture.session.scalars.return_value = iter((fixture.definition,))
    statuses = workflow_definition_admission_statuses(cast(Session, fixture.session))
    assert statuses[0].role_protocol_version == "local-embedding/1.0"
    assert statuses[0].accepts_new_work
