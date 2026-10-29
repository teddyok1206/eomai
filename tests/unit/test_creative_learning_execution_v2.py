"""Explicit source-visual execution successor; no Codex/DB/systemd side effects."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.state_machine import JobState
from eom_workflow.control_plane import (
    ResolvedExecutionPlanV27,
    ResolvedExecutionPlanV28,
    parse_creative_learning_execution_plan,
)
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.creative_learning_profile import (
    creative_learning_profile,
    creative_learning_profile_for_protocol,
)
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner import external_item_learning_preparation as preparation
from eom_workflow_runner import external_item_learning_start as start
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.external_item_learning_admission import (
    validate_external_item_learning_submission,
)
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_external_item_learning_execution import _execute, _fixture
from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_execution_resolver import (
    _published_preset,
    _resolve,
    _Session,
)
from tests.unit.test_external_item_learning_preparation import _case as prepare_case
from tests.unit.test_external_item_learning_start import _case as start_case
from tests.unit.test_external_item_learning_workflow_admission import OPERATOR, _definition

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_profile_closes_definition_protocol_plan_and_result_family(version):
    profile = creative_learning_profile(version)
    assert profile == creative_learning_profile_for_protocol(profile.role_protocol)
    parsed = parse_creative_learning_execution_plan(_plan(successor=version == "2.0.0"))
    assert parsed.schema_version == profile.plan_schema_version
    assert parsed.resolver_version == profile.resolver_version
    assert parsed.workflow_definition_version == version


@pytest.mark.parametrize("unknown", ["latest", "3.0.0", "workflow-role/1.35.0"])
def test_profile_never_substitutes_a_latest_family(unknown):
    with pytest.raises(ValueError):
        creative_learning_profile(unknown)
    with pytest.raises(ValueError):
        creative_learning_profile_for_protocol(unknown)


def test_successor_plan_schema_mirror_hash_and_previous_family_isolation():
    name = "resolved-execution-plan-v28.schema.json"
    canonical = ROOT / "schemas/workflow/control-plane" / name
    assert (
        canonical.read_bytes()
        == (ROOT / "packages/workflow/eom_workflow/resources/control-plane" / name).read_bytes()
    )
    from hashlib import sha256

    assert sha256(canonical.read_bytes()).hexdigest() == (
        "64d503c519de79418e5609759bbdb4b19127d9b037d272018faf235e4fe9dda2"
    )
    value = _plan(successor=True)
    validate_control_contract("resolved-execution-plan-v28", value)
    ResolvedExecutionPlanV28.model_validate(value)
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV27.model_validate(value)
    with pytest.raises(SchemaError):
        validate_control_contract("resolved-execution-plan-v27", value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_definition_version", "1.0.0"),
        ("resolver_version", "27.0.0"),
        ("plan_sha256", "sha256:" + "0" * 64),
    ],
)
def test_plan_successor_does_not_accept_mixed_or_changed_pins(field, value):
    document = deepcopy(_plan(successor=True))
    document[field] = value
    if field != "plan_sha256":
        document["plan_sha256"] = content_sha256(
            {k: v for k, v in document.items() if k != "plan_sha256"}
        )
    with pytest.raises(ValidationError):
        parse_creative_learning_execution_plan(document)


@pytest.mark.parametrize(
    "version,key",
    [
        ("1.0.0", "external-item-learning"),
        ("2.0.0", "creative-source-learning"),
        ("1.0.0", "creative-source-learning"),
        ("2.0.0", "external-item-learning"),
    ],
)
def test_active_definition_requires_its_exact_preset_purpose(version, key):
    profile = creative_learning_profile(version)
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key=key,
        external_item_learning_work=_plan()["work_input"],
    )
    kwargs = dict(
        definition=_definition(successor=version == "2.0.0"),
        request=request,
        actor_type="human",
        actor_id=OPERATOR,
    )
    if key == profile.preset_key:
        assert validate_external_item_learning_submission(**kwargs) == request
    else:
        with pytest.raises(WorkflowError):
            validate_external_item_learning_submission(**kwargs)


def test_successor_resolver_pins_and_replays_without_adopting_old_plan():
    logical, revision = _published_preset(successor=True)
    session = _Session(logical, revision)
    work = ResolvedExecutionPlanV28.model_validate(_plan(successor=True)).work_input
    plan = _resolve(session, work, protocol="workflow-role/1.34.0")
    assert isinstance(plan, ResolvedExecutionPlanV28)
    replay = Mock()
    replay.scalar.return_value = session.added[0]
    assert _resolve(replay, work, protocol="workflow-role/1.34.0") == plan
    with pytest.raises(ControlPlaneError, match="different pinned inputs"):
        _resolve(replay, work, protocol="workflow-role/1.33.0")
    replay.add.assert_not_called()


def test_successor_preparation_uses_separate_purpose_without_starting(monkeypatch):
    value = prepare_case(monkeypatch, successor=True)
    result = preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    assert result.selection.plan_sha256 == value.plan.plan_sha256
    request = value.create.call_args.kwargs["request"]
    assert request.execution_preset_key == "creative-source-learning"
    assert value.new_step.call_args.kwargs["result_schema"] == "external-item-learning-result@2.0"
    assert value.step.state == "READY" and value.step.platform_job_id is None


def test_successor_start_preserves_supported_queue_and_pinned_family(monkeypatch):
    value = start_case(monkeypatch, successor=True)
    result = start.start_prepared_external_item_learning(value.session, **value.args)
    assert result.command_created
    assert value.enqueue.call_args.kwargs["source"] == "creative_item_learning"
    assert value.owner.reauthorize.call_count == 2


@pytest.mark.parametrize(
    "successor,schema",
    [
        (False, "external-item-learning-result@2.0"),
        (True, "external-item-learning-result@1.0"),
    ],
)
def test_cross_family_result_is_rejected_before_capacity_or_launch(
    monkeypatch, tmp_path, successor, schema
):
    value = _fixture(monkeypatch, tmp_path, successor=successor)
    with pytest.raises(ControlPlaneError) as error:
        _execute(value, result_schema=schema)
    assert error.value.code == "CONTROL_CREATIVE_CONTEXT_INVALID"
    value.orchestrator.capacity.claim.assert_not_called()
    value.worker.run_prepared.assert_not_called()
    value.commit.assert_not_called()


def test_v2_executes_validates_source_and_commits_through_existing_owner(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path, successor=True)
    result = _execute(value, result_schema="external-item-learning-result@2.0")
    assert result.status == "SUCCEEDED"
    assert (
        value.worker.prepare_structured_workspace.call_args.kwargs["input_document"][
            "protocol_version"
        ]
        == "workflow-role/1.34.0"
    )
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_called_once()
    assert value.source.call_count == 4
    assert value.materialize.call_args.kwargs["creative_page_publisher"] is value.publisher


@pytest.mark.parametrize("terminal", [JobState.SUCCEEDED, JobState.FAILED])
def test_successor_terminal_replay_preserves_history_and_does_not_run_again(
    monkeypatch, tmp_path, terminal
):
    value = _fixture(monkeypatch, tmp_path, successor=True)
    job = _execute(value, result_schema="external-item-learning-result@2.0")
    assert job.status == "SUCCEEDED"
    job.status = terminal.value  # fixture-only terminal history, not a DB repair
    monkeypatch.setattr(value.orchestrator, "_job_by_idempotency_key", lambda _key: job)
    monkeypatch.setattr(value.orchestrator, "_resume_pre_execution_job", lambda _job_id: terminal)
    assert _execute(value, result_schema="external-item-learning-result@2.0") is job
    assert job.status == terminal.value
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_called_once()


def test_successor_revoked_source_after_model_never_commits(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path, successor=True)
    value.source.side_effect = [None, None, None, ValueError("revoked")]
    result = _execute(value, result_schema="external-item-learning-result@2.0")
    assert result.status == "FAILED"
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_not_called()
